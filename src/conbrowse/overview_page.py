from typing import Callable

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk, Pango  # noqa: E402

from conbrowse.config import (
    OVERVIEW_CARD_HEIGHT,
    OVERVIEW_CARD_WIDTH,
    OVERVIEW_PREVIEW_FONT,
)
from conbrowse.models import AppState, WindowInfo


class OverviewPage(Gtk.ScrolledWindow):
    def __init__(self, on_activate: Callable[[str], None]) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._on_activate = on_activate
        self._flow = Gtk.FlowBox()
        self._flow.set_valign(Gtk.Align.START)
        self._flow.set_max_children_per_line(4)
        self._flow.set_min_children_per_line(1)
        self._flow.set_row_spacing(12)
        self._flow.set_column_spacing(12)
        self._flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flow.set_homogeneous(True)
        self._flow.set_margin_top(12)
        self._flow.set_margin_bottom(12)
        self._flow.set_margin_start(12)
        self._flow.set_margin_end(12)
        self.add(self._flow)

        self._cards: dict[str, _Card] = {}

    def set_state(self, state: AppState) -> None:
        seen: set[str] = set()
        for w in state.windows:
            seen.add(w.id)
            card = self._cards.get(w.id)
            if card is None:
                card = _Card(w, self._on_activate)
                self._cards[w.id] = card
                self._flow.add(card)
            else:
                card.update(w)
        for stale_id in list(self._cards):
            if stale_id in seen:
                continue
            card = self._cards.pop(stale_id)
            parent = card.get_parent()
            if parent is not None:
                parent.destroy()
        self._flow.show_all()


class _Card(Gtk.EventBox):
    def __init__(self, info: WindowInfo, on_activate: Callable[[str], None]) -> None:
        super().__init__()
        self._window_id = info.id
        self._on_activate = on_activate

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self.add(frame)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        frame.add(box)

        self._title = Gtk.Label(xalign=0.0)
        self._title.set_ellipsize(Pango.EllipsizeMode.END)
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        self._title.set_attributes(attrs)
        box.pack_start(self._title, False, False, 0)

        self._preview = Gtk.Label(xalign=0.0, yalign=0.0)
        self._preview.set_line_wrap(False)
        self._preview.set_single_line_mode(False)
        self._preview.set_selectable(False)
        self._preview.set_ellipsize(Pango.EllipsizeMode.NONE)
        font = Pango.FontDescription.from_string(OVERVIEW_PREVIEW_FONT)
        self._preview.override_font(font)
        self._preview.set_size_request(OVERVIEW_CARD_WIDTH, OVERVIEW_CARD_HEIGHT)
        box.pack_start(self._preview, True, True, 0)

        self.update(info)

        self.connect("button-press-event", self._on_click)

    def update(self, info: WindowInfo) -> None:
        marker = " *" if info.active else ""
        self._title.set_text(f"{info.index}: {info.name}{marker}")
        self._preview.set_text(info.preview or "")

    def _on_click(self, _widget, _event) -> bool:
        self._on_activate(self._window_id)
        return True
