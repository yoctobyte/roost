"""Transport for reaching a tmux server, locally or over ssh.

A "box" is identified by its ssh destination as typed -- an alias from
~/.ssh/config, or user@host. The same host reached as two different
users is two different boxes, because each user has their own tmux
server on their own socket. A destination of None means "this machine",
which runs the command directly rather than looping back through ssh.

Nothing here ever prompts. BatchMode=yes turns a missing key into a
fast, classifiable failure instead of a password prompt that would hang
a poll forever.
"""

import os
import shlex
import subprocess

CONNECT_TIMEOUT = 5
CONTROL_PERSIST = "60s"
# Generous ceiling for a single call; ConnectTimeout covers the common
# unreachable case long before this fires.
RUN_TIMEOUT = 30

# Transport failure: unreachable, auth refused, bad host key.
SSH_FAILURE = 255
# Shell could not find the binary.
COMMAND_NOT_FOUND = 127

READY = "ready"
NEEDS_KEY = "needs-key"
OFFLINE = "offline"
NO_TMUX = "no-tmux"


def control_path() -> str:
    """Path template for the multiplexed control socket.

    Kept short on purpose: Unix socket paths cap out around 104 bytes,
    and a template under a long state directory silently breaks
    multiplexing -- which costs ~300ms per call instead of ~30ms. %C is
    a hash of (host, port, user), so it is unique per destination.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, "roost-cm-%C")


def ssh_args(dest: str) -> list[str]:
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={CONNECT_TIMEOUT}",
        "-o", "ControlMaster=auto",
        "-o", f"ControlPath={control_path()}",
        "-o", f"ControlPersist={CONTROL_PERSIST}",
        dest,
    ]


def run(
    dest: str | None,
    argv: list[str],
    stdin: str | None = None,
) -> tuple[int, str, str]:
    """Run `argv` on `dest`. Returns (returncode, stdout, stderr).

    Remotely the argv is re-parsed by the login shell, so every element
    is quoted -- our tmux format strings are full of #{} and $, and
    window names can contain spaces and quotes.
    """
    if dest is None:
        cmd = list(argv)
    else:
        cmd = ssh_args(dest) + [" ".join(shlex.quote(a) for a in argv)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin,
            timeout=RUN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return SSH_FAILURE, "", "timed out"
    except FileNotFoundError as exc:
        return COMMAND_NOT_FOUND, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def classify(returncode: int, stderr: str) -> str | None:
    """Map a failed call to a box state, or None if it is not a
    transport/availability problem and the caller should interpret it.

    Both "unreachable" and "auth refused" surface as 255 and are only
    separable by stderr -- and it is the auth case that should trigger
    the offer to install a key, so the distinction matters.
    """
    if returncode == SSH_FAILURE:
        lowered = stderr.lower()
        if "permission denied" in lowered or "no supported authentication" in lowered:
            return NEEDS_KEY
        return OFFLINE
    if returncode == COMMAND_NOT_FOUND:
        return NO_TMUX
    return None


def resolve(dest: str) -> dict[str, str]:
    """Resolve a destination through ~/.ssh/config without connecting.

    Lets an alias be shown as the user@host it really means, and lets
    two entries that resolve to the same box be spotted as duplicates.
    """
    try:
        proc = subprocess.run(
            ["ssh", "-G", dest], capture_output=True, text=True, timeout=10
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}
    if proc.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(" ")
        if key in ("user", "hostname", "port") and key not in out:
            out[key] = value
    return out


DEFAULT_KEY = "~/.ssh/id_ed25519"


def has_local_key() -> bool:
    """Whether this machine has any ssh public key to offer a box."""
    ssh_dir = os.path.expanduser("~/.ssh")
    try:
        return any(n.endswith(".pub") for n in os.listdir(ssh_dir))
    except OSError:
        return False


def key_install_command(dest: str) -> str:
    """Shell to run interactively in a terminal to authorise this box.

    Deliberately a real command in a real pty rather than something
    roost drives: the passphrase and the box's password stay between
    the user and ssh, roost never sees or stores them, and the
    unknown-host-key prompt -- which BatchMode can only fail on -- gets
    answered here, once, by a human.
    """
    quoted = shlex.quote(dest)
    key = DEFAULT_KEY
    return (
        f'if [ ! -f {key}.pub ]; then '
        f'echo "No ssh key yet -- creating one."; '
        f'ssh-keygen -t ed25519 -f {key} || exit 1; fi; '
        f'ssh-copy-id -i {key}.pub {quoted}'
    )


def probe(dest: str | None) -> tuple[str, str]:
    """Check whether a box is usable. Returns (state, detail).

    `tmux list-sessions` exits 1 with no output when the server simply
    is not running, which is a perfectly healthy box with zero sessions
    -- not an error. Treating that as failure would report every idle
    box as broken.
    """
    rc, _out, err = run(dest, ["tmux", "list-sessions", "-F", "#{session_name}"])
    if rc == 0:
        return READY, ""
    state = classify(rc, err)
    if state is not None:
        return state, err.strip().splitlines()[0] if err.strip() else ""
    return READY, ""
