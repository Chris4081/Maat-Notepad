# maat_notepad.py

import html as html_lib
import json
import hashlib
import math
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

try:
    import AppKit
    import Foundation
    import WebKit
except Exception:
    AppKit = None
    Foundation = None
    WebKit = None

APP_NAME = "MAAT Notepad"
VERSION = "2026.04"
APP_SUPPORT = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "MAATNotepad")
SAVE_FILE = os.path.join(APP_SUPPORT, "notes.json")
UI_STATE_FILE = os.path.join(APP_SUPPORT, "ui_state.json")
DEFAULT_WINDOW_GEOMETRY = "1200x680"
DEFAULT_NOTE_SORT_MODE = "updated_desc"
NOTE_SORT_CHOICES = [
    ("updated_desc", "Zuletzt geändert: Neu -> Alt"),
    ("updated_asc", "Zuletzt geändert: Alt -> Neu"),
    ("created_desc", "Erstellt: Neu -> Alt"),
    ("created_asc", "Erstellt: Alt -> Neu"),
    ("title_asc", "Titel: A -> Z"),
    ("title_desc", "Titel: Z -> A"),
    ("maat_desc", "MAAT: Hoch -> Niedrig"),
    ("maat_asc", "MAAT: Niedrig -> Hoch"),
]
DUTI_CANDIDATES = [
    "/opt/homebrew/bin/duti",   # Apple Silicon (Homebrew)
    "/usr/local/bin/duti",      # Intel (Homebrew)
    "/opt/local/bin/duti",      # MacPorts
]
# --- MAAT Principles ---
PRINCIPLES = ["Harmonie", "Balance", "Schöpfungskraft", "Verbundenheit", "Respekt"]

# Heuristische Keyword-Listen (stammorientiert, damit deutsche Flexionen besser erkannt werden)
KW = {
    "Harmonie": ["harmoni", "ruh", "still", "fried", "klar", "einklang", "kohaer", "ordn", "sanft", "stabil", "gelass", "stimm"],
    "Balance": ["balanc", "gleichgewicht", "ausgleich", "mass", "prioris", "grenz", "struktur", "rhythm", "abwäg", "kompromiss", "zugleich", "einers", "anderers"],
    "Schöpfungskraft": ["idee", "erschaff", "kreier", "design", "erfind", "experiment", "vision", "inspiration", "prototyp", "neu", "entwurf", "innovation", "verknuepf"],
    "Verbundenheit": ["wir", "gemeinsam", "verbund", "netzwerk", "team", "dialog", "bezieh", "teil", "community", "mitgefuehl", "zusammen", "partner", "unterstuetz"],
    "Respekt": ["bitte", "danke", "acht", "wuerd", "respekt", "achtsam", "fair", "inklusi", "ethik", "grenz", "freund", "hoeflich", "ruecksicht", "wertschaetz"],
}

MAAT_SIGNAL_WORDS = {
    "calm": ["ruh", "klar", "sanft", "fried", "gelass", "stabil", "geordnet", "kohaer", "sachlich"],
    "connectors": ["aber", "jedoch", "zugleich", "sowohl", "weder", "trotzdem", "wahrend", "hingegen", "einers", "anderers", "gleichzeitig"],
    "creative": ["neu", "idee", "vision", "experiment", "warum", "wie", "moeglich", "entwurf", "skizz", "alternativ", "ungewoehn", "inspiration"],
    "collective": ["wir", "uns", "gemeinsam", "zusammen", "miteinand", "team", "partner", "netzwerk", "bezieh", "unterstuetz", "helfen", "dialog"],
    "dialogue": ["dialog", "frage", "antwort", "feedback", "gespraech", "zuhoer", "abstimm", "austausch"],
    "courtesy": ["bitte", "danke", "respekt", "freund", "hoeflich", "achtsam", "fair", "wertschaetz", "ruecksicht", "sorgfalt"],
    "harsh": ["idiot", "dumm", "bloed", "scheiss", "fick", "hass", "wertlos", "laecher", "peinlich", "aggress", "nervig", "veracht"],
}

# Farbcodierung pro Prinzip (für Score-Anzeige)
COLORS = {
    "Harmonie": "#3FA7D6",
    "Balance": "#8F8F8F",
    "Schöpfungskraft": "#E07A5F",
    "Verbundenheit": "#2A9D8F",
    "Respekt": "#6C63FF",
}
# Duti Helper
def _find_duti_path():
    """
    Sucht 'duti' zuverlässig:
    - PATH (shutil.which)
    - Homebrew-Standardpfade
    - /usr/local/bin (Intel Macs)
    """
    # 1) PATH
    p = shutil.which("duti")
    if p:
        return p
    # 2) Typische Brew-Orte
    for cand in ("/opt/homebrew/bin/duti", "/usr/local/bin/duti"):
        if os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return None
# --- Storage helpers ---

    
def _get_bundle_identifier(self) -> str:
    # Versuche, die Bundle-ID aus der Info.plist zu lesen (wenn als .app gebündelt)
    try:
        exe = os.path.abspath(sys.argv[0])
        # …/My.app/Contents/MacOS/MyBinary → Info.plist daneben
        if ".app/" in exe:
            info = os.path.join(exe.split(".app/")[0] + ".app", "Contents", "Info.plist")
            with open(info, "rb") as f:
                plist = plistlib.load(f)
            bid = plist.get("CFBundleIdentifier")
            if bid:
                return bid
    except Exception:
        pass
    # Fallback: eure im Spec verwendete ID
    return "com.maat.notepad"

def _has_duti(self) -> bool:
    return shutil.which("duti") is not None

def ensure_storage():
    os.makedirs(APP_SUPPORT, exist_ok=True)
    if not os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    if not os.path.exists(UI_STATE_FILE):
        with open(UI_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_default_ui_state(), f)


def _default_ui_state():
    return {
        "root_sash": 320,
        "right_sash": 460,
        "nav_open": False,
        "window_geometry": DEFAULT_WINDOW_GEOMETRY,
        "window_state": "normal",
        "note_sort_mode": DEFAULT_NOTE_SORT_MODE,
    }

def _safe_join_lines(*parts):
    parts = [p for p in parts if p is not None and p != ""]
    return "\n".join(parts)


class _HTMLPreviewParser(HTMLParser):
    def __init__(self, widget):
        super().__init__(convert_charrefs=True)
        self.widget = widget
        self.document_title = ""
        self._title_parts = []
        self._preview_stack = []
        self._list_stack = []
        self._link_stack = []
        self._ignore_depth = 0
        self._capture_title = False
        self._in_pre = False
        self._tail = ""

    def _insert(self, text: str, tags=()):
        if not text:
            return
        tags = tuple(dict.fromkeys([tag for tag in (tags or ()) if tag]))
        if tags:
            self.widget.insert("end", text, tags)
        else:
            self.widget.insert("end", text)
        self._tail = (self._tail + text)[-16:]

    def _trailing_newlines(self) -> int:
        count = 0
        for ch in reversed(self._tail):
            if ch == "\n":
                count += 1
            else:
                break
        return count

    def _ensure_newlines(self, count: int):
        if not self._tail:
            return
        missing = count - self._trailing_newlines()
        if missing > 0:
            self._insert("\n" * missing)

    def _active_tags(self):
        tags = []
        seen = set()
        for _html_tag, preview_tag in self._preview_stack:
            if preview_tag and preview_tag not in seen:
                tags.append(preview_tag)
                seen.add(preview_tag)
        return tuple(tags)

    def _push(self, html_tag: str, preview_tag: str | None = None):
        self._preview_stack.append((html_tag, preview_tag))

    def _pop(self, html_tag: str):
        for i in range(len(self._preview_stack) - 1, -1, -1):
            if self._preview_stack[i][0] == html_tag:
                self._preview_stack.pop(i)
                break

    def _start_block(self):
        self._ensure_newlines(2)

    def _emit_inline(self, text: str):
        if self._in_pre:
            self._insert(text, self._active_tags())
            return
        text = re.sub(r"\s+", " ", text)
        if not text.strip():
            return
        if not self._tail or self._tail.endswith((" ", "\n")):
            text = text.lstrip()
        if text:
            self._insert(text, self._active_tags())

    def handle_starttag(self, tag, attrs):
        tag = (tag or "").lower()
        attrs = dict(attrs or [])

        if tag in {"script", "style"}:
            self._ignore_depth += 1
            return
        if tag == "title":
            self._capture_title = True
            return
        if self._ignore_depth:
            return

        if tag in {"p", "div", "section", "article", "header", "footer", "main", "aside", "nav"}:
            self._start_block()
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._start_block()
            level = int(tag[1]) if len(tag) == 2 and tag[1].isdigit() else 3
            preview_tag = "pv_h1" if level == 1 else "pv_h2" if level == 2 else "pv_h3"
            self._push(tag, preview_tag)
            return
        if tag == "blockquote":
            self._start_block()
            self._push(tag, "pv_quote")
            return
        if tag in {"ul", "ol"}:
            self._start_block()
            self._list_stack.append({"kind": tag, "index": 1})
            return
        if tag == "li":
            self._ensure_newlines(1 if self._list_stack else 2)
            marker = "- "
            if self._list_stack and self._list_stack[-1]["kind"] == "ol":
                marker = f"{self._list_stack[-1]['index']}. "
                self._list_stack[-1]["index"] += 1
            self._insert(marker, ("pv_list",))
            self._push(tag, "pv_list")
            return
        if tag == "br":
            self._insert("\n")
            return
        if tag == "hr":
            self._start_block()
            self._insert("-" * 28 + "\n\n", ("pv_rule",))
            return
        if tag == "pre":
            self._start_block()
            self._in_pre = True
            self._push(tag, "pv_codeblock")
            return
        if tag in {"code", "kbd", "samp"} and not self._in_pre:
            self._push(tag, "pv_inline_code")
            return
        if tag in {"strong", "b"}:
            self._push(tag, "pv_strong")
            return
        if tag in {"em", "i", "cite", "dfn"}:
            self._push(tag, "pv_em")
            return
        if tag == "a":
            self._push(tag, "pv_link")
            self._link_stack.append((attrs.get("href") or "").strip())
            return
        if tag == "img":
            label = (attrs.get("alt") or attrs.get("src") or "Bild").strip()
            self._start_block()
            self._insert(f"[Bild: {label}]\n\n", ("pv_caption",))

    def handle_endtag(self, tag):
        tag = (tag or "").lower()

        if tag == "title":
            self._capture_title = False
            self.document_title = " ".join(self._title_parts).strip()
            return
        if tag in {"script", "style"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if self._ignore_depth:
            return

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._pop(tag)
            self._ensure_newlines(2)
            return
        if tag in {"p", "div", "section", "article", "header", "footer", "main", "aside", "nav"}:
            self._ensure_newlines(2)
            return
        if tag == "blockquote":
            self._pop(tag)
            self._ensure_newlines(2)
            return
        if tag == "li":
            self._pop(tag)
            self._insert("\n")
            return
        if tag in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
            self._ensure_newlines(2)
            return
        if tag == "pre":
            self._pop(tag)
            self._in_pre = False
            self._ensure_newlines(2)
            return
        if tag in {"code", "kbd", "samp"} and not self._in_pre:
            self._pop(tag)
            return
        if tag in {"strong", "b", "em", "i", "cite", "dfn"}:
            self._pop(tag)
            return
        if tag == "a":
            self._pop(tag)
            href = self._link_stack.pop() if self._link_stack else ""
            if href:
                self._insert(f" ({href})", ("pv_link_url",))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if not data:
            return
        if self._capture_title:
            title = re.sub(r"\s+", " ", data).strip()
            if title:
                self._title_parts.append(title)
            return
        if self._ignore_depth:
            return
        self._emit_inline(data)


class _NativeHTMLWebViewPreview:
    def __init__(self):
        if not (AppKit and Foundation and WebKit):
            raise RuntimeError("Native WebView ist nicht verfügbar.")

        app = AppKit.NSApplication.sharedApplication()
        try:
            app.activateIgnoringOtherApps_(False)
        except Exception:
            pass

        style_mask = (
            getattr(AppKit, "NSWindowStyleMaskTitled", 1 << 0)
            | getattr(AppKit, "NSWindowStyleMaskClosable", 1 << 1)
            | getattr(AppKit, "NSWindowStyleMaskMiniaturizable", 1 << 2)
            | getattr(AppKit, "NSWindowStyleMaskResizable", 1 << 3)
        )
        rect = Foundation.NSMakeRect(180.0, 120.0, 980.0, 760.0)
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            style_mask,
            getattr(AppKit, "NSBackingStoreBuffered", 2),
            False,
        )
        window.setReleasedWhenClosed_(False)
        window.setTitle_("MAAT Notepad - WebView-Vorschau")

        config = WebKit.WKWebViewConfiguration.alloc().init()
        webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(window.contentView().bounds(), config)
        webview.setAutoresizingMask_(
            getattr(AppKit, "NSViewWidthSizable", 2) | getattr(AppKit, "NSViewHeightSizable", 16)
        )
        window.contentView().addSubview_(webview)

        self.window = window
        self.webview = webview

    def _base_url(self, base_dir: str | None):
        if not base_dir:
            return None
        path = str(Path(base_dir).expanduser())
        try:
            return Foundation.NSURL.fileURLWithPath_isDirectory_(path, True)
        except Exception:
            try:
                return Foundation.NSURL.fileURLWithPath_(path)
            except Exception:
                return None

    def show(self):
        try:
            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass
        self.window.makeKeyAndOrderFront_(None)

    def hide(self):
        try:
            self.window.orderOut_(None)
        except Exception:
            pass

    def close(self):
        try:
            self.window.close()
        except Exception:
            pass

    def load_html(self, html: str, *, base_dir: str | None = None, title: str | None = None):
        if title:
            self.window.setTitle_(f"MAAT Notepad - WebView - {title}")
        else:
            self.window.setTitle_("MAAT Notepad - WebView-Vorschau")
        self.webview.loadHTMLString_baseURL_(html or "", self._base_url(base_dir))
        self.show()

def _compose_text_for_file(self, path: str) -> str:
    """
    Erzeugt den finalen Dateitext.
    - Für .py: setzt (einmalig) eine '# <Titel>'-Zeile voran.
      Respektiert eine vorhandene Shebang-Zeile ('#!...').
      Idempotent: setzt den Header nicht doppelt.
    - Für andere Endungen: Inhalt unverändert (kein Titel-Header).
    """
    ext     = os.path.splitext(path)[1].lower()
    title   = (self.title_var.get() or "").strip()
    content = self.text.get("1.0", "end-1c")

    if ext != ".py":
        # Falls du bei .txt/.md den Titel als erste Zeile möchtest,
        # kannst du hier optional hinzufügen:
        # if title:
        #     return f"{title}\n\n{content}"
        return content

    # ----- .py: Header vorbereiten -----
    header = f"# {title}" if title else "#"

    # Inhalt in Zeilen splitten (ohne abschließendes '\n')
    lines = content.splitlines()

    # Shebang behandeln (nur ganz oben, z.B. '#!/usr/bin/env python3')
    shebang = None
    start_ix = 0
    if lines and lines[0].startswith("#!"):
        shebang = lines[0]
        start_ix = 1  # tatsächlicher Code (bzw. Header) startet dahinter

    # Prüfen, ob der Header bereits vorhanden ist (idempotent)
    if start_ix < len(lines):
        first_code_line = lines[start_ix].strip()
        if first_code_line == header.strip():
            # Header ist schon da → unverändert zurück (mit Shebang, falls vorhanden)
            if shebang is not None:
                return "\n".join([shebang] + lines[1:]) + ("\n" if content.endswith("\n") else "")
            else:
                return content

    # Header einfügen (nach Shebang, falls vorhanden)
    new_lines = []
    if shebang is not None:
        new_lines.append(shebang)
    new_lines.append(header)

    # Leere Zeile nach Header nur, wenn gleich mehr Inhalt folgt
    if start_ix < len(lines):
        new_lines.append("")  # Abstand zum restlichen Code
        new_lines.extend(lines[start_ix:])
    # Wenn es keinen weiteren Inhalt gibt, bleibt nur Header (und evtl. Shebang)

    # Endet Originaltext mit Newline? – dann auch hier sauber abschließen
    result = "\n".join(new_lines)
    if content.endswith("\n"):
        result += "\n"
    return result

def _save_current_to_path(self, path: str) -> bool:
    """Speichert den aktuellen Editor-Inhalt exakt auf 'path'.
    Nutzt _compose_text_for_file, setzt bei .py den Code-Modus und resetet Dirty."""
    try:
        title   = (self.title_var.get() or "").strip()
        content = self.text.get("1.0", "end-1c")

        data = self._compose_text_for_file(path, title, content)

        with open(path, "w", encoding="utf-8") as f:
            f.write(data)

        # Optional: Bei .py in Code-Modus wechseln (für bessere UX)
        if path.lower().endswith(".py") and not self.code_mode.get():
            self.code_mode.set(True)
            self._toggle_code_mode()

        self._dirty = False
        messagebox.showinfo("Gespeichert", f"Datei gespeichert:\n{path}")
        return True

    except Exception as e:
        messagebox.showerror("Speichern", f"Konnte Datei nicht speichern:\n{e}")
        return False
        
def load_notes():
    ensure_storage()
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _atomic_write_json(path, data):
    """Replace JSON only after a complete write; retain the old file on failure."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".maat-", suffix=".tmp", delete=False) as f:
            temporary = f.name
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save_notes(notes):
    _atomic_write_json(SAVE_FILE, notes)

def load_ui_state():
    ensure_storage()
    try:
        with open(UI_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            state = _default_ui_state()
            if isinstance(data, dict):
                state.update(data)
            return state
    except Exception:
        return _default_ui_state()

def save_ui_state(root_sash, right_sash):
    ensure_storage()
    state = load_ui_state()
    state["root_sash"] = int(root_sash)
    state["right_sash"] = int(right_sash)
    _atomic_write_json(UI_STATE_FILE, state)

# --- Scoring ---
def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(10.0, float(value))), 2)


def _normalize_analysis_token(token: str) -> str:
    token = (token or "").lower()
    token = (
        token.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    token = re.sub(r"[^a-z0-9]+", "", token)
    for suffix in (
        "lichkeiten", "lichkeiten", "igkeit", "igkeiten", "heiten", "keiten", "ungen",
        "lichkeit", "lichkeit", "ismus", "ation", "ieren", "ierend", "ische", "ischen",
        "lich", "keit", "heit", "ung", "end", "ern", "est", "er", "en", "em", "es", "e", "n", "s",
    ):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    return token


def _analysis_tokens(text: str) -> list[str]:
    raw_tokens = re.findall(r"[A-Za-zÄÖÜäöüß0-9]+", text or "")
    tokens = []
    for raw in raw_tokens:
        norm = _normalize_analysis_token(raw)
        if norm:
            tokens.append(norm)
    return tokens


def _root_matches(token: str, root: str) -> bool:
    if not token or not root:
        return False
    if len(root) <= 3:
        return token == root
    if token == root or token.startswith(root):
        return True
    return len(root) >= 6 and root in token


def _keyword_profile(tokens: list[str], roots: list[str], scale: float = 18.0):
    norm_roots = [_normalize_analysis_token(root) for root in (roots or []) if root]
    hit_count = 0.0
    matched_roots = set()

    for token in tokens:
        for root in norm_roots:
            if _root_matches(token, root):
                hit_count += 1.0
                matched_roots.add(root)
                break

    token_count = len(tokens)
    density = _clip01(hit_count / max(1.0, token_count / max(1.0, scale)))
    coverage = _clip01(len(matched_roots) / max(2.0, len(norm_roots) * 0.34))
    return hit_count, density, coverage


def score_text(text: str):
    tokens = _analysis_tokens(text)
    if not tokens:
        scores = {p: 0.0 for p in PRINCIPLES}
        return scores, 0.0

    token_count = len(tokens)
    unique_ratio = len(set(tokens)) / max(1, token_count)
    diversity = _clip01((unique_ratio - 0.22) / 0.5)
    length_gate = _clip01(0.22 + 0.78 * min(1.0, token_count / 36.0))
    sentences = [part.strip() for part in re.split(r"[.!?\n]+", text or "") if part.strip()]
    sentence_count = max(1, len(sentences))
    sentence_flow = _clip01(sentence_count / 4.0)
    question_openness = _clip01((text.count("?") / max(1.0, sentence_count)) * 0.8)
    exclaim_pressure = _clip01(text.count("!") / max(1.0, sentence_count * 2.0))

    letters = [ch for ch in (text or "") if ch.isalpha()]
    uppercase_ratio = (sum(1 for ch in letters if ch.isupper()) / len(letters)) if len(letters) >= 12 else 0.0

    _, calm_density, _ = _keyword_profile(tokens, MAAT_SIGNAL_WORDS["calm"], scale=20.0)
    _, connector_density, _ = _keyword_profile(tokens, MAAT_SIGNAL_WORDS["connectors"], scale=20.0)
    _, creative_density, _ = _keyword_profile(tokens, MAAT_SIGNAL_WORDS["creative"], scale=18.0)
    _, collective_density, _ = _keyword_profile(tokens, MAAT_SIGNAL_WORDS["collective"], scale=18.0)
    _, dialogue_density, _ = _keyword_profile(tokens, MAAT_SIGNAL_WORDS["dialogue"], scale=18.0)
    _, courtesy_density, _ = _keyword_profile(tokens, MAAT_SIGNAL_WORDS["courtesy"], scale=20.0)
    _, harsh_density, _ = _keyword_profile(tokens, MAAT_SIGNAL_WORDS["harsh"], scale=18.0)

    aggression = _clip01(harsh_density * 0.9 + uppercase_ratio * 0.9 + exclaim_pressure * 0.45)
    openness = _clip01(question_openness * 0.55 + creative_density * 0.45)

    principle_profiles = {}
    for principle in PRINCIPLES:
        _hits, density, coverage = _keyword_profile(tokens, KW[principle], scale=18.0)
        principle_profiles[principle] = {"density": density, "coverage": coverage}

    scores = {}
    scores["Harmonie"] = _clamp_score(
        1.90 * length_gate
        + 0.70 * (1.0 - aggression)
        + 4.9 * principle_profiles["Harmonie"]["coverage"]
        + 2.15 * principle_profiles["Harmonie"]["density"]
        + 1.35 * (0.45 * calm_density + 0.35 * sentence_flow + 0.20 * diversity)
        - 2.05 * aggression
    )
    scores["Balance"] = _clamp_score(
        1.75 * length_gate
        + 0.60 * (1.0 - aggression)
        + 4.85 * principle_profiles["Balance"]["coverage"]
        + 2.10 * principle_profiles["Balance"]["density"]
        + 1.45 * (0.55 * connector_density + 0.25 * sentence_flow + 0.20 * diversity)
        - 0.75 * aggression
    )
    scores["Schöpfungskraft"] = _clamp_score(
        1.30 * length_gate
        + 0.40 * diversity
        + 4.75 * principle_profiles["Schöpfungskraft"]["coverage"]
        + 2.15 * principle_profiles["Schöpfungskraft"]["density"]
        + 1.95 * (0.45 * creative_density + 0.35 * diversity + 0.20 * openness)
        - 0.45 * aggression
    )
    scores["Verbundenheit"] = _clamp_score(
        1.65 * length_gate
        + 0.55 * (1.0 - aggression)
        + 4.85 * principle_profiles["Verbundenheit"]["coverage"]
        + 2.10 * principle_profiles["Verbundenheit"]["density"]
        + 1.70 * (0.45 * collective_density + 0.35 * dialogue_density + 0.20 * sentence_flow)
        - 0.85 * aggression
    )
    scores["Respekt"] = _clamp_score(
        3.40
        + 1.60 * length_gate
        + 2.80 * principle_profiles["Respekt"]["coverage"]
        + 1.55 * principle_profiles["Respekt"]["density"]
        + 1.65 * (0.45 * courtesy_density + 0.20 * sentence_flow + 0.20 * dialogue_density + 0.15 * diversity)
        - 5.85 * aggression
    )

    stability = min(
        scores["Respekt"],
        math.prod(max(0.2, scores[p]) for p in ("Harmonie", "Balance", "Schöpfungskraft", "Verbundenheit")) ** 0.25,
    )
    mean_score = sum(scores[p] for p in PRINCIPLES) / len(PRINCIPLES)
    spread = max(scores.values()) - min(scores.values())
    coherence = max(0.0, 10.0 - spread * 0.9)
    maat_value = _clamp_score(0.45 * mean_score + 0.40 * stability + 0.15 * coherence)
    return scores, maat_value

# --- App ---
class MaatNotepad(tk.Tk):
    def __init__(self):
        super().__init__()
        self._dirty = False
        self.ui_state = load_ui_state()
        self.title(APP_NAME)
        self.geometry(str(self.ui_state.get("window_geometry", DEFAULT_WINDOW_GEOMETRY) or DEFAULT_WINDOW_GEOMETRY))
        self.configure(bg="#F5F5F7")

        # Frühe Referenzen (verhindert hasattr-Fehler)
        self.run_btn = None
        self._score_ctrl = None
        self.status_wrap = None
        self.status_label = None
        self.doc_type_badge = None
        self.preview_btn = None
        self.preview_wrap = None
        self.preview_divider = None
        self.preview_header = None
        self.preview_text = None
        self._native_html_webview = None
        self._preview_image_ref = None
        self._preview_image_refs = []
        self._last_tex_pdf_path = None
        self._python_interpreter_override = None
        self._doc_tabs = []
        self._active_tab_index = -1
        self._next_tab_serial = 1
        self._loading_tab_state = False
        self._session_persist_after = None
        self._note_select_after = None

        # --- Daten & Status ---
        self.notes = load_notes()
        self.current_id = None
        self.filter_principle = None
        self.editor_font_family = self._sanitize_editor_font_family(self.ui_state.get("editor_font_family", "Menlo"))
        self.editor_font_size = self._sanitize_editor_font_size(self.ui_state.get("editor_font_size", 16))
        self.note_sort_mode_var = tk.StringVar(value=self._normalize_note_sort_mode(self.ui_state.get("note_sort_mode", DEFAULT_NOTE_SORT_MODE)))
        self.external_file = None
        self._hl_after = None
        self._pending_external_paths = []
        self._editor_font_dialog = None

        # --- Editor-Status ---
        self.code_mode = tk.BooleanVar(value=False)
        self.preview_mode = tk.BooleanVar(value=bool(self.ui_state.get("markdown_preview", True)))
        self._fixed_gutter = True
        self._gutter_width = 6
        self._gutter_width_max = 14
        self._lint_results = []   # [(tag, start_index, end_index, message, level)]
        self._preview_after = None

        # --- Theme-Status (muss vor Menüs/Layout existieren) ---
        self.dark_mode = tk.BooleanVar(value=bool(self.ui_state.get("dark_mode", False)))

        # --- Statusbar-State (einmalig) ---
        self.status_var = tk.StringVar(value="Bereit")
        self._status_timer = None

        # UI bauen
        self._restoring_tab_session = True
        self._build_menu()
        self._build_layout()
        self._restore_tab_session()
        self._restoring_tab_session = False
        self._refresh_list()

        # === STATUSBAR (einmalig) ===
        self.status_wrap = tk.Frame(self, bd=0, highlightthickness=0)
        self.status_wrap.pack(side="bottom", fill="x")
        self.status_label = tk.Label(
            self.status_wrap,
            textvariable=self.status_var,
            anchor="w", padx=8, pady=3
        )
        self.status_label.pack(fill="x")

        # Titel-Änderungen spiegeln sofort in der Statusbar
        try:
            self.title_var.trace_add("write", lambda *_: self._on_title_change())
        except Exception:
            pass

        # Initiale Statuszeile setzen
        self._update_statusbar()

        # Theme anwenden (inkl. Statusbar)
        self._apply_theme()
        self.after(80, self._restore_window_settings)

        # Sonstiges
        self._duti_path = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._install_global_scroll()
        self._install_macos_open_document_handler()

        # --- Suche-Status robust initialisieren ---
        if not hasattr(self, "_last_find") or not isinstance(getattr(self, "_last_find"), dict):
            self._last_find = {"q": "", "case": False, "regex": False}

### Optische Erweiterung
    def _install_global_scroll(self):
        """Erlaube Scrollen, auch wenn der Editor nicht fokussiert ist."""
        # Vertikal (Trackpad/MouseWheel)
        try:
            self.bind_all("<MouseWheel>", self._on_global_mousewheel)
        except Exception:
            pass
        # Horizontal scrollen mit Shift
        try:
            self.bind_all("<Shift-MouseWheel>", self._on_global_mousewheel)
        except Exception:
            pass
        # X11 (einige Linux/Remote-Umgebungen)
        try:
            self.bind_all("<Button-4>", lambda e: self._on_global_button_wheel(e, +1))
            self.bind_all("<Button-5>", lambda e: self._on_global_button_wheel(e, -1))
        except Exception:
            pass

    def _on_global_mousewheel(self, event):
        """Leite Wheel-Events an den Text weiter (macOS/Win)."""
        try:
            w = getattr(self, "text", None)
            if not w or not w.winfo_exists():
                return "break"
            # event.delta: +120 / -120 (Win), ±(viel kleiner) (macOS/Trackpad)
            step = -1 if event.delta > 0 else 1
            if (event.state & 0x0001):  # Shift gedrückt → horizontal
                w.xview_scroll(step, "units")
            else:
                w.yview_scroll(step, "units")
            return "break"
        except Exception:
            return "break"

    def _on_global_button_wheel(self, event, direction):
        """X11 Fallback: Button-4/5 → vertikal scrollen."""
        try:
            w = getattr(self, "text", None)
            if not w or not w.winfo_exists():
                return "break"
            w.yview_scroll(-1 if direction > 0 else 1, "units")
            return "break"
        except Exception:
            return "break"


##Optische Erweiterung Ende


    def _about(self):
        """Einfacher Über-Dialog."""
        try:
            app = APP_NAME
        except Exception:
            app = "MAAT Notepad"
        try:
            ver = VERSION
        except Exception:
            ver = "1.0"

        txt = (
            f"{app} – Version {ver}\n"
            "Erstellt von Maat KI & Christof Krieg \n\n"
            "Ein minimalistischer Notiz‑ und Code‑Editor mit MAAT‑Analyse,\n"
            "Dark‑Mode, Statusleiste, Linter‑Support und mehr."
        )
        try:
            messagebox.showinfo("Über …", txt)
        except Exception:
            # Fallback, falls messagebox in früher Initialisierungsphase hakt
            print(txt)
    # ---------------------------------------------------------------------
    # Theme anwenden – Statusbar mit einfärben
    # ---------------------------------------------------------------------
    def _apply_theme(self):
        c = self._palette()

        def _theme_classic_widget_tree(widget):
            try:
                skip_widgets = {getattr(self, "new_tab_btn", None)}
                for doc in getattr(self, "_doc_tabs", []) or []:
                    skip_widgets.add(doc.get("_tab_button"))
                    skip_widgets.add(doc.get("_tab_close_button"))

                if widget not in skip_widgets:
                    if isinstance(widget, tk.Button):
                        text = str(widget.cget("text") or "").strip()
                        subtle = text in {"×", "+", "◀︎", "▶︎", "✕"}
                        widget.configure(
                            bg=(c["btn_subtle_bg"] if subtle else c["btn_bg"]),
                            fg=(c["btn_muted_fg"] if subtle else c["btn_fg"]),
                            activebackground=(c["btn_subtle_hover"] if subtle else c["btn_hover"]),
                            activeforeground=c["btn_fg"],
                            highlightbackground=c["btn_border"],
                            highlightcolor=c["accent"],
                            relief="flat",
                            bd=1,
                            padx=10,
                            pady=6,
                        )
                    elif isinstance(widget, tk.Checkbutton):
                        widget.configure(
                            bg=c["panel"],
                            fg=c["fg"],
                            activebackground=c["panel"],
                            activeforeground=c["fg"],
                            selectcolor=c["sunken"],
                            highlightbackground=c["panel"],
                            highlightcolor=c["accent"],
                        )
                    elif isinstance(widget, tk.Radiobutton):
                        widget.configure(
                            bg=c["panel"],
                            fg=c["fg"],
                            activebackground=c["panel"],
                            activeforeground=c["fg"],
                            selectcolor=c["sunken"],
                            highlightbackground=c["panel"],
                            highlightcolor=c["accent"],
                        )
            except Exception:
                pass

            try:
                for child in widget.winfo_children():
                    _theme_classic_widget_tree(child)
            except Exception:
                pass

        # --- Root / Fenster ---
        try:
            self.configure(bg=c["bg"])
        except Exception:
            pass

        try:
            self.option_add("*Button.Background", c["btn_bg"])
            self.option_add("*Button.Foreground", c["btn_fg"])
            self.option_add("*Button.activeBackground", c["btn_hover"])
            self.option_add("*Button.activeForeground", c["btn_fg"])
            self.option_add("*Button.highlightBackground", c["btn_border"])
            self.option_add("*Button.highlightColor", c["accent"])
            self.option_add("*Checkbutton.Background", c["panel"])
            self.option_add("*Checkbutton.Foreground", c["fg"])
            self.option_add("*Checkbutton.activeBackground", c["panel"])
            self.option_add("*Checkbutton.activeForeground", c["fg"])
            self.option_add("*Radiobutton.Background", c["panel"])
            self.option_add("*Radiobutton.Foreground", c["fg"])
            self.option_add("*Radiobutton.activeBackground", c["panel"])
            self.option_add("*Radiobutton.activeForeground", c["fg"])
        except Exception:
            pass

        #Linter verdunkeln:
        try:
            self._update_tooltip_theme()
        except Exception:
            pass

        # --- Linke Spalte: Container + Liste + Suchleiste ---
        # Container links (falls gemerkt)
        try:
            if hasattr(self, "left_pane") and self.left_pane.winfo_exists():
                self.left_pane.configure(bg=c.get("listbg", c["bg"]))
        except Exception:
            pass

        # Listbox
        try:
            self.listbox.configure(
                bg=c["listbg"], fg=c["listfg"],
                selectbackground=c["selbg"], selectforeground=c["selfg"]
            )
        except Exception:
            pass

        # Suchleiste (Rahmen + Label + Entry)
        try:
            if hasattr(self, "search_bar") and self.search_bar.winfo_exists():
                self.search_bar.configure(bg=c.get("listbg", c["bg"]))
                # alle Kinder der Suchleiste einfärben
                for w in self.search_bar.winfo_children():
                    if isinstance(w, tk.Label):
                        w.configure(bg=c.get("listbg", c["bg"]), fg=c["fg"])
                    # ttk.Buttons bekommen ihre Farbe über ttk.Style (kommt unten)
            if hasattr(self, "search_actions") and self.search_actions.winfo_exists():
                self.search_actions.configure(bg=c.get("listbg", c["bg"]))
            if hasattr(self, "search_entry") and self.search_entry.winfo_exists():
                self.search_entry.configure(
                    bg=c["panel"], fg=c["fg"],
                    insertbackground=c["cursor"],
                    highlightthickness=1,
                    highlightbackground=c["border"],
                    highlightcolor=c["border"]
                )
        except Exception:
            pass

        # Filter-Hinweis
        try:
            if hasattr(self, "filter_hint") and self.filter_hint.winfo_exists():
                self.filter_hint.configure(bg=c.get("listbg", c["bg"]), fg=c["fg"])
        except Exception:
            pass
        try:
            if getattr(self, "sort_menu_btn", None) and self.sort_menu_btn.winfo_exists():
                self.sort_menu_btn.configure(text="Sortierung")
        except Exception:
            pass



        # --- Editor ---
        try:
            if getattr(self, "right_pane", None) and self.right_pane.winfo_exists():
                self.right_pane.configure(
                    bg=c["bg"],
                    highlightbackground=c["border"],
                    highlightcolor=c["accent"],
                )
            if hasattr(self, "editor_wrap") and self.editor_wrap.winfo_exists():
                self.editor_wrap.configure(
                    bg=c["panel"],
                    highlightthickness=1,
                    highlightbackground=c["border"],
                    highlightcolor=c["accent"],
                    bd=0,
                )
            self.text.configure(
                bg=c["panel"], fg=c["fg"],
                insertbackground=c["cursor"],
                selectbackground=c["selbg"], selectforeground=c["selfg"],
                highlightbackground=c["panel"],
                highlightcolor=c["panel"],
                highlightthickness=0,
                spacing1=1,
                spacing3=1,
            )
        except Exception:
            pass

        try:
            if getattr(self, "preview_divider", None) and self.preview_divider.winfo_exists():
                self.preview_divider.configure(bg=c["border"])
            if getattr(self, "preview_wrap", None) and self.preview_wrap.winfo_exists():
                self.preview_wrap.configure(
                    bg=c["sunken"],
                    highlightthickness=1,
                    highlightbackground=c["border"],
                    highlightcolor=c["accent"],
                    bd=0,
                )
            if getattr(self, "preview_header", None) and self.preview_header.winfo_exists():
                self.preview_header.configure(bg=c["toolbar"], fg=c["fg"])
            if getattr(self, "preview_text", None) and self.preview_text.winfo_exists():
                self.preview_text.configure(
                    bg=c["sunken"],
                    fg=c["fg"],
                    selectbackground=c["selbg"],
                    selectforeground=c["selfg"],
                    highlightbackground=c["sunken"],
                    highlightcolor=c["sunken"],
                    highlightthickness=0,
                )
                self.preview_text.tag_configure("pv_h1", foreground=c["fg"], font=("Georgia", 22, "bold"), spacing1=8, spacing3=6)
                self.preview_text.tag_configure("pv_h2", foreground=c["fg"], font=("Georgia", 18, "bold"), spacing1=6, spacing3=4)
                self.preview_text.tag_configure("pv_h3", foreground=c["fg"], font=("Georgia", 16, "bold"), spacing1=4, spacing3=4)
                self.preview_text.tag_configure("pv_quote", foreground=c["muted"], lmargin1=24, lmargin2=24, spacing1=2, spacing3=4)
                self.preview_text.tag_configure("pv_list", lmargin1=24, lmargin2=42, spacing1=1, spacing3=2)
                self.preview_text.tag_configure("pv_inline_code", foreground=("#F78C6C" if self.dark_mode.get() else "#B54708"), background=c["codebg"], font=("Menlo", 13))
                self.preview_text.tag_configure("pv_codeblock", foreground=c["fg"], background=c["codebg"], font=("Menlo", 13), lmargin1=16, lmargin2=16, spacing1=2, spacing3=2)
                self.preview_text.tag_configure("pv_code_fence", foreground=c["muted"], background=c["codebg"], font=("Menlo", 12, "italic"), lmargin1=16, lmargin2=16, spacing1=4, spacing3=2)
                self.preview_text.tag_configure("pv_link", foreground=c["accent"], underline=1)
                self.preview_text.tag_configure("pv_link_url", foreground=c["muted"], font=("Menlo", 12))
                self.preview_text.tag_configure("pv_strong", font=("Georgia", 15, "bold"))
                self.preview_text.tag_configure("pv_em", font=("Georgia", 15, "italic"))
                self.preview_text.tag_configure("pv_rule", foreground=c["border"], justify="center", spacing1=6, spacing3=6)
                self.preview_text.tag_configure("pv_caption", foreground=c["muted"], font=("Menlo", 11), justify="center", spacing1=8)
        except Exception:
            pass

        # Gutter / Zeilennummern
        try:
            self.linenos.configure(bg=c["gutter"], fg=c["gutterfg"])
        except Exception:
            pass
        try:
            for sb in (getattr(self, "vscroll", None), getattr(self, "hscroll", None)):
                if sb and sb.winfo_exists():
                    sb.configure(
                        bg=c["btn_subtle_bg"],
                        activebackground=c["btn_hover"],
                        troughcolor=c["panel"],
                        highlightbackground=c["panel"],
                        highlightcolor=c["panel"],
                        borderwidth=0,
                        elementborderwidth=0,
                        relief="flat",
                    )
        except Exception:
            pass

        # --- Titelzeile ---
        try:
            if hasattr(self, "title_row") and self.title_row.winfo_exists():
                self.title_row.configure(bg=c["panel"])
                # Label "Titel:"
                for w in self.title_row.winfo_children():
                    if isinstance(w, tk.Label):
                        w.configure(bg=c["panel"], fg=c["fg"])
            # Entry
            if hasattr(self, "title_entry") and self.title_entry.winfo_exists():
                self.title_entry.configure(
                    bg=c["panel"], fg=c["fg"],
                    insertbackground=c["cursor"],
                    highlightthickness=1,
                    highlightbackground=c["border"],
                    highlightcolor=c["border"]
                )
        except Exception:
            pass

        try:
            _theme_classic_widget_tree(self)
        except Exception:
            pass

        try:
            if getattr(self, "tab_strip", None) and self.tab_strip.winfo_exists():
                self.tab_strip.configure(bg=c["toolbar"])
            if getattr(self, "tab_inner", None) and self.tab_inner.winfo_exists():
                self.tab_inner.configure(bg=c["toolbar"])
            if getattr(self, "new_tab_btn", None) and self.new_tab_btn.winfo_exists():
                self.new_tab_btn.configure(
                    bg=c["btn_subtle_bg"],
                    fg=c["btn_fg"],
                    highlightbackground=c["btn_border"],
                    highlightcolor=c["accent"],
                    highlightthickness=1,
                    relief="flat",
                    bd=0,
                )
            for doc in getattr(self, "_doc_tabs", []) or []:
                frame = doc.get("_tab_frame")
                btn = doc.get("_tab_button")
                close_btn = doc.get("_tab_close_button")
                is_active = bool(doc.get("_tab_active"))
                if frame and frame.winfo_exists():
                    frame.configure(
                        bg=(c["panel"] if is_active else c["toolbar"]),
                        highlightbackground=(c["accent"] if is_active else c["border"]),
                    )
                if btn and btn.winfo_exists():
                    btn.configure(
                        bg=(c["btn_bg"] if is_active else c["btn_subtle_bg"]),
                        fg=c["btn_fg"],
                        highlightbackground=(c["accent"] if is_active else c["btn_border"]),
                        highlightcolor=c["accent"],
                        highlightthickness=1,
                        relief="flat",
                        bd=0,
                    )
                if close_btn and close_btn.winfo_exists():
                    close_btn.configure(
                        bg=(c["btn_bg"] if is_active else c["btn_subtle_bg"]),
                        fg=c["btn_muted_fg"],
                        highlightbackground=(c["accent"] if is_active else c["btn_border"]),
                        highlightcolor=c["accent"],
                        highlightthickness=1,
                        relief="flat",
                        bd=0,
                    )
        except Exception:
            pass

        # --- Such-Tags im Text ---
        try:
            self.text.tag_configure("find_all",     background=c["find_all"])
            self.text.tag_configure("find_current", background=c["find_cur"])
            self.text.tag_configure("current_line", background=c["current"])
            self.text.tag_configure("brace_match", background=c["brace_match_bg"])
            self.text.tag_configure("brace_error", background=c["brace_error_bg"])
            self.linenos.tag_configure("current_line_no", background=c["current_no_bg"], foreground=c["current_no_fg"])
        except Exception:
            pass

        # --- Syntax-Farben (bleibt wie bei dir) ---
        try:
            if self.dark_mode.get():
                self.text.tag_configure("kw",  foreground="#59B0FF")
                self.text.tag_configure("def", foreground="#C586C0")
                self.text.tag_configure("str", foreground="#CE9178")
                self.text.tag_configure("com", foreground="#6A9955")
                self.text.tag_configure("num", foreground="#B5CEA8")
                self.text.tag_configure("dec", foreground="#D19A66")
                self.text.tag_configure("md_h1", foreground="#82AAFF", font=self._editor_heading_font(2, 18))
                self.text.tag_configure("md_h2", foreground="#C792EA", font=self._editor_heading_font(1, 16))
                self.text.tag_configure("md_h3", foreground="#7FDBCA", font=self._editor_heading_font(0, 15))
                self.text.tag_configure("md_em", foreground="#FFCB6B")
                self.text.tag_configure("md_code", foreground="#F78C6C", background=c["codebg"])
                self.text.tag_configure("md_link", foreground="#89DDFF", underline=1)
                self.text.tag_configure("md_quote", foreground="#8A97A8")
                self.text.tag_configure("md_list", foreground="#C3E88D")
                self.text.tag_configure("md_fence", foreground="#6A9955")
                self.text.tag_configure("tex_cmd", foreground="#82AAFF")
                self.text.tag_configure("tex_env", foreground="#C792EA")
                self.text.tag_configure("tex_math", foreground="#FFCB6B")
                self.text.tag_configure("tex_comment", foreground="#6A9955")
            else:
                self.text.tag_configure("kw",  foreground="#0057B8")
                self.text.tag_configure("def", foreground="#8A2BE2")
                self.text.tag_configure("str", foreground="#D2691E")
                self.text.tag_configure("com", foreground="#6A9955")
                self.text.tag_configure("num", foreground="#1E88E5")
                self.text.tag_configure("dec", foreground="#B00020")
                self.text.tag_configure("md_h1", foreground="#0F6CBD", font=self._editor_heading_font(2, 18))
                self.text.tag_configure("md_h2", foreground="#7A3EF0", font=self._editor_heading_font(1, 16))
                self.text.tag_configure("md_h3", foreground="#00796B", font=self._editor_heading_font(0, 15))
                self.text.tag_configure("md_em", foreground="#9A6700")
                self.text.tag_configure("md_code", foreground="#B54708", background=c["codebg"])
                self.text.tag_configure("md_link", foreground="#0B57D0", underline=1)
                self.text.tag_configure("md_quote", foreground="#5F6B7A")
                self.text.tag_configure("md_list", foreground="#1D7F3F")
                self.text.tag_configure("md_fence", foreground="#6A9955")
                self.text.tag_configure("tex_cmd", foreground="#0F6CBD")
                self.text.tag_configure("tex_env", foreground="#7A3EF0")
                self.text.tag_configure("tex_math", foreground="#9A6700")
                self.text.tag_configure("tex_comment", foreground="#6A9955")
        except Exception:
            pass
        # Lint-Farben je nach Theme
        try:
            if self.dark_mode.get():
                self.text.tag_configure("lint_error",   background="#3b1f22")  # dunkles Rot
                self.text.tag_configure("lint_warning", background="#3b351f")  # dunkles Gelb
                self.text.tag_configure("lint_note",    background="#1f2f3b")  # dunkles Blau
            else:
                self.text.tag_configure("lint_error",   background="#FFD6D6")  # zart Rot
                self.text.tag_configure("lint_warning", background="#FFF2CC")  # zart Gelb
                self.text.tag_configure("lint_note",    background="#DCEBFF")  # zart Blau
        except Exception:
            pass

        # --- Score/Prinzipien-Bereich (falls gemerkt) ---
        try:
            if hasattr(self, "score_pane") and self.score_pane.winfo_exists():
                self.score_pane.configure(bg=c.get("bg", "#000"))
                for w in self.score_pane.winfo_children():
                    try:
                        w.configure(bg=c.get("bg", "#000"))
                    except Exception:
                        pass
                # Labels in den Score-Frames umfärben
                for p in getattr(self, "score_labels", {}).values():
                    # p ist StringVar; finde typische Label drumherum nicht direkt → iterativ
                    pass  # nichts zu tun, Farben kommen über parent-Frames/Labels unten
                # einmal durch alle Kinder laufen und Labels einfärben
                for f in self.score_pane.winfo_children():
                    for w in f.winfo_children():
                        if isinstance(w, tk.Label):
                            try:
                                w.configure(bg=c.get("bg", "#000"), fg=c["fg"])
                            except Exception:
                                pass
        except Exception:
            pass
        try:
            if getattr(self, "code_toggle_btn", None) and self.code_toggle_btn.winfo_exists():
                self.code_toggle_btn.configure(
                    bg=c["panel"],
                    fg=c["fg"],
                    activebackground=c["panel"],
                    activeforeground=c["fg"],
                    selectcolor=c["sunken"],
                    highlightbackground=c["panel"],
                    highlightcolor=c["accent"],
                    highlightthickness=1,
                )
        except Exception:
            pass

        # --- ttk-Style angleichen ---
        try:
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except Exception:
                pass
            style.configure(
                "TButton",
                foreground=c["btn_fg"],
                background=c["btn_bg"],
                bordercolor=c["btn_border"],
                lightcolor=c["btn_border"],
                darkcolor=c["btn_border"],
                relief="flat",
                borderwidth=1,
                focusthickness=1,
                focuscolor=c["accent"],
                padding=(10, 6),
            )
            style.map(
                "TButton",
                background=[
                    ("disabled", c["toolbar"]),
                    ("pressed", c["btn_pressed"]),
                    ("active", c["btn_hover"]),
                ],
                foreground=[
                    ("disabled", c["muted"]),
                    ("pressed", c["btn_fg"]),
                    ("active", c["btn_fg"]),
                ],
                bordercolor=[
                    ("focus", c["accent"]),
                    ("active", c["accent"]),
                    ("!active", c["btn_border"]),
                ],
                lightcolor=[
                    ("pressed", c["btn_pressed"]),
                    ("active", c["btn_hover"]),
                    ("!active", c["btn_border"]),
                ],
                darkcolor=[
                    ("pressed", c["btn_pressed"]),
                    ("active", c["btn_hover"]),
                    ("!active", c["btn_border"]),
                ],
            )
            style.configure(
                "TMenubutton",
                foreground=c["btn_fg"],
                background=c["btn_bg"],
                bordercolor=c["btn_border"],
                lightcolor=c["btn_border"],
                darkcolor=c["btn_border"],
                relief="flat",
                borderwidth=1,
                focusthickness=1,
                focuscolor=c["accent"],
                padding=(10, 6),
                arrowcolor=c["btn_fg"],
            )
            style.map(
                "TMenubutton",
                background=[
                    ("disabled", c["toolbar"]),
                    ("pressed", c["btn_pressed"]),
                    ("active", c["btn_hover"]),
                ],
                foreground=[
                    ("disabled", c["muted"]),
                    ("pressed", c["btn_fg"]),
                    ("active", c["btn_fg"]),
                ],
                bordercolor=[
                    ("focus", c["accent"]),
                    ("active", c["accent"]),
                    ("!active", c["btn_border"]),
                ],
                arrowcolor=[
                    ("disabled", c["muted"]),
                    ("pressed", c["btn_fg"]),
                    ("active", c["btn_fg"]),
                ],
            )
            style.configure(
                "Toolbutton",
                foreground=c["btn_fg"],
                background=c["btn_subtle_bg"],
                bordercolor=c["btn_border"],
                lightcolor=c["btn_border"],
                darkcolor=c["btn_border"],
                relief="flat",
                borderwidth=1,
                focusthickness=1,
                focuscolor=c["accent"],
                padding=(8, 5),
            )
            style.map(
                "Toolbutton",
                background=[
                    ("disabled", c["toolbar"]),
                    ("selected", c["btn_pressed"]),
                    ("pressed", c["btn_pressed"]),
                    ("active", c["btn_subtle_hover"]),
                ],
                foreground=[
                    ("disabled", c["muted"]),
                    ("selected", c["btn_fg"]),
                    ("pressed", c["btn_fg"]),
                    ("active", c["btn_fg"]),
                ],
                bordercolor=[
                    ("focus", c["accent"]),
                    ("selected", c["accent"]),
                    ("active", c["accent"]),
                    ("!active", c["btn_border"]),
                ],
            )
            style.configure("TCheckbutton", foreground=c["fg"], background=c["panel"])
            style.configure("TRadiobutton", foreground=c["fg"], background=c["panel"])
            style.configure("TLabel", foreground=c["fg"], background=c["panel"])
        except Exception:
            pass

        # --- Statusbar einfärben ---
        try:
            if getattr(self, "status_wrap", None):
                self.status_wrap.configure(bg=c["panel"])
            if getattr(self, "status_label", None):
                self.status_label.configure(bg=c["panel"], fg=c["muted"], font=("Menlo", 11))
        except Exception:
            pass
        # Score-Pane & Prinzipien-Kästchen dunkel einfärben
        try:
            # Hintergrund des ganzen Score-Panes anpassen
            if getattr(self, "score_pane", None):
                self.score_pane.configure(bg=c["panel"])

            # Die Reihe, in der die Scores liegen, kann in einigen
            # Setups 'scores_row' heißen; falls nicht separat gemerkt,
            # reicht es, die Kinder-Frames aus self._score_boxes zu färben.
            if hasattr(self, "_score_boxes"):
                for box in self._score_boxes:
                    f = box["frame"]
                    name_lbl = box["name"]
                    val_lbl  = box["value"]
                    p = box["principle"]

                    # dunkler Hintergrund fürs Kästchen
                    try:
                        f.configure(bg=c["panel"])
                    except Exception:
                        pass

                    # Titel (z.B. "Balance") bleibt farbig (COLORS[p]),
                    # aber auf dunklem Hintergrund
                    try:
                        name_lbl.configure(bg=c["panel"], fg=COLORS[p])
                    except Exception:
                        pass

                    # Wert in normaler Vordergrundfarbe
                    try:
                        val_lbl.configure(bg=c["panel"], fg=c["fg"])
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            if getattr(self, "linter_frame", None) and self.linter_frame.winfo_exists():
                self.linter_frame.configure(bg=c["panel"])
                if getattr(self, "linter_label", None):
                    self.linter_label.configure(bg=c["panel"], fg=c["fg"])
                if getattr(self, "linter_list", None):
                    self.linter_list.configure(
                        bg=c["listbg"],
                        fg=c["listfg"],
                        selectbackground=c["selbg"],
                        selectforeground=c["selfg"],
                    )
        except Exception:
            pass
        try:
            if getattr(self, "doc_type_badge", None):
                self._update_editor_chrome()
        except Exception:
            pass
        try:
            self._schedule_preview_update()
        except Exception:
            pass
        # --- Schnellsuche einfärben ---
        try:
            if getattr(self, "quickfind_row", None) and self.quickfind_row.winfo_exists():
                # Hintergrund an Score‑Pane anlehnen
                base = c.get("panel", c["bg"])
                self.quickfind_row.configure(bg=base)
                if getattr(self, "quickfind_label", None):
                    self.quickfind_label.configure(bg=base, fg=c["fg"])
                if getattr(self, "quickfind_entry", None):
                    self.quickfind_entry.configure(
                        bg=c["panel"], fg=c["fg"],
                        insertbackground=c["cursor"],
                        highlightthickness=1,
                        highlightbackground=c["border"],
                        highlightcolor=c["border"]
                    )
        except Exception:
            pass



        self._apply_design_details(c)

        def _clear_lint_marks(self):
            """Entfernt alle bisherigen Lint-Markierungen."""
            try:
                self.text.tag_remove("lint_error", "1.0", "end")
                self.text.tag_remove("lint_warning", "1.0", "end")
                self.text.tag_remove("lint_note", "1.0", "end")
                # dynamische msg-tags entfernen
                if hasattr(self, "_lint_msg_map"):
                    for t in list(self._lint_msg_map.keys()):
                        try:
                            self.text.tag_delete(t)
                        except Exception:
                            pass
                self._lint_msg_map = {}
                self._lint_results = []
            except Exception:
                pass

        def _tk_index_from_linecol(self, line: int, col: int) -> str:
            """
            Flake8 liefert 1-basierte line/col; Tk nutzt 1-basige line und 0-basige col.
            """
            line = max(1, int(line))
            col0 = max(0, int(col) - 1)
            return f"{line}.{col0}"
            # In der Klasse MaatNotepad (z.B. unter deinen Storage/Helper-Methoden)

        def _run_linter(self):
            """Läuft flake8 über den aktuellen Editor-Inhalt und markiert Findings farbig.
            - bevorzugt externes 'flake8' Binary (shutil.which)
            - Fallback: In-Process über flake8.main.application (funktioniert in PyInstaller/.app)
            """
            import os
            import re
            import sys
            import io
            import shutil
            import tempfile
            import subprocess
            import contextlib
            from tkinter import messagebox

            # 1) Temp-Datei mit deiner Header-Logik schreiben
            try:
                with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
                    tmp_path = tmp.name
                    try:
                        data = self._compose_text_for_file(tmp_path)
                    except Exception:
                        title = (self.title_var.get() or "").strip()
                        content = self.text.get("1.0", "end-1c")
                        data = (f"# {title}\n\n{content}") if title else content
                    tmp.write(data)
            except Exception as e:
                try:
                    messagebox.showerror("Linter", f"Konnte Temp-Datei nicht schreiben:\n{e}")
                except Exception:
                    pass
                return

            # 2) Vorherige Markierungen löschen
            try:
                self._clear_lint_marks()
            except Exception:
                pass

            # 3) flake8 ausführen – erst externes Binary, sonst In-Process
            fmt = "%(path)s:%(row)d:%(col)d: %(code)s %(text)s"
            out = ""
            err = ""
            used_external = False

            flake_bin = shutil.which("flake8")
            if flake_bin:
                # Externes Binary (sicher in .app/normal)
                cmd = [flake_bin, "--format=" + fmt, "--max-line-length=120", tmp_path]
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    out = proc.stdout or ""
                    err = proc.stderr or ""
                    used_external = True
                except Exception as e:
                    err = str(e)

            if not used_external:
                # Fallback: In-Process (keine '-m'-Aufrufe nötig)
                try:
                    import flake8.main.application as fl_app
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        app = fl_app.Application()
                        app.initialize([
                            "flake8",
                            "--format=" + fmt,
                            "--max-line-length=120",
                            tmp_path,
                        ])
                        app.run_checks()
                        app.report()
                    out = buf.getvalue()
                except Exception as e:
                    try:
                        messagebox.showwarning(
                            "Linter",
                            "flake8 ist nicht als Binary auffindbar und In‑Process‑Ausführung ist fehlgeschlagen.\n\n"
                            "Tipp: Installiere flake8 im System/venv:\n\n    pip install flake8\n\n"
                            f"Fehler: {e}"
                        )
                    except Exception:
                        pass
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                    return

            # 4) Ausgabe parsen und markieren
            findings = []
            pat = re.compile(rf"^{re.escape(tmp_path)}:(\d+):(\d+):\s+([A-Z]\d+)\s+(.*)$")

            for line in out.splitlines():
                m = pat.match(line.strip())
                if not m:
                    continue
                row_s, col_s, code, msg = m.groups()
                row, col = int(row_s), int(col_s)

                if code.startswith(("E", "F")):
                    tag, level = "lint_error", "error"
                elif code.startswith("W"):
                    tag, level = "lint_warning", "warning"
                else:
                    tag, level = "lint_note", "note"

                si = self._tk_index_from_linecol(row, col)
                ei = f"{row}.end"

                uniq = f"lint_msg_{len(findings)}"
                try:
                    self.text.tag_add(tag, si, ei)
                    self.text.tag_add(uniq, si, ei)
                except Exception:
                    continue

                if not hasattr(self, "_lint_msg_map"):
                    self._lint_msg_map = {}
                self._lint_msg_map[uniq] = f"{code}: {msg}"

                findings.append((tag, si, ei, f"{code}: {msg}", level))

            self._lint_results = findings

            # 5) Status & Sichtbarkeit
            if findings:
                n_err = sum(1 for *_, lvl in findings if lvl == "error")
                n_warn = sum(1 for *_, lvl in findings if lvl == "warning")
                n_note = sum(1 for *_, lvl in findings if lvl == "note")
                self.status_message(f"Linter: {n_err} Fehler, {n_warn} Warnungen, {n_note} Hinweise")
                try:
                    self.text.see(findings[0][1])
                except Exception:
                    pass
            else:
                self.status_message("Linter: keine Probleme ✓")

            # 6) Temp-Datei aufräumen
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    def _has_duti(self) -> bool:
        """Ist das CLI-Tool 'duti' installiert?"""
        return self._find_duti_path() is not None

    def _run_duti(self, args: list[str], timeout: int = 8) -> subprocess.CompletedProcess:
        """Startet 'duti' mit robustem PATH."""
        duti = self._find_duti_path()
        if not duti:
            raise FileNotFoundError("duti nicht gefunden")
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/opt/local/bin",
            env.get("PATH", "")
        ])
        return subprocess.run([duti] + list(args), capture_output=True, text=True, timeout=timeout, env=env)

    def _get_bundle_identifier(self) -> str:
        """Bundle-ID aus der .app lesen; Fallback auf feste ID."""
        try:
            exe = os.path.abspath(sys.argv[0])
            if ".app/" in exe:
                info_plist = os.path.join(exe.split(".app/")[0] + ".app", "Contents", "Info.plist")
                with open(info_plist, "rb") as f:
                    plist = plistlib.load(f)
                bid = plist.get("CFBundleIdentifier")
                if bid:
                    return bid
        except Exception:
            pass
        return "com.maat.notepad"  # Fallback

    def _find_duti_path(self) -> str | None:
        """Findet 'duti' robust auch im App-Bundle- oder Homebrew-Kontext."""
        cached = getattr(self, "_duti_path", None)
        if cached and os.path.exists(cached):
            return cached

        for cand in DUTI_CANDIDATES:
            if os.path.exists(cand) and os.access(cand, os.X_OK):
                self._duti_path = cand
                return cand

        try:
            out = subprocess.check_output(
                ["/usr/bin/env", "zsh", "-lc", "command -v duti || true"],
                text=True,
            ).strip()
            if out and os.path.exists(out):
                self._duti_path = out
                return out
        except Exception:
            pass

        extra_path = os.pathsep.join(
            ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", os.environ.get("PATH", "")]
        )
        found = shutil.which("duti", path=extra_path)
        if found:
            self._duti_path = found
            return found
        return None

    def _apply_file_assoc_with_duti(self, exts=None, utis=None):
        """
        Setzt Dateiverknüpfungen via duti (nur macOS).
        exts: Liste wie ['.txt', '.md', '.py']
        utis: Liste von Tupeln (uti, role), z.B. ('public.python-script','editor')
        Rückgabe: (ok_list, errs_list) – errs_list enthält (target, fehlertext)
        """
        import sys, subprocess

        ok, errs = [], []

        # Nur auf macOS sinnvoll
        if sys.platform != "darwin":
            errs.append(("platform", "Nur unter macOS unterstützt"))
            return ok, errs

        duti = self._find_duti_path()
        if not duti:
            errs.append(("duti", "Nicht gefunden. Installiere per 'brew install duti'."))
            return ok, errs

        bid = self._get_bundle_identifier()  # z.B. 'com.maat.notepad'

        # --- Extensions (.txt, .md, ...) ---
        if exts:
            for ext in exts:
                e = (ext or "").lstrip(".").lower()
                if not e:
                    errs.append((str(ext), "Ungültige Extension"))
                    continue
                try:
                    proc = subprocess.run([duti, "-s", bid, e, "all"],
                                          capture_output=True, text=True)
                    if proc.returncode == 0:
                        ok.append(f"ext:{e}")
                    else:
                        msg = proc.stderr.strip() or proc.stdout.strip() or f"duti rc={proc.returncode}"
                        errs.append((f"ext:{e}", msg))
                except Exception as ex:
                    errs.append((f"ext:{e}", str(ex)))

        # --- UTIs (z.B. public.python-script) ---
        if utis:
            for item in utis:
                try:
                    uti, role = item
                except Exception:
                    errs.append((str(item), "UTI-Eintrag muss (uti, role) sein"))
                    continue
                uti  = (uti  or "").strip()
                role = (role or "editor").strip()
                if not uti:
                    errs.append((str(item), "Leere UTI"))
                    continue
                try:
                    proc = subprocess.run([duti, "-s", bid, uti, role],
                                          capture_output=True, text=True)
                    if proc.returncode == 0:
                        ok.append(f"uti:{uti}:{role}")
                    else:
                        msg = proc.stderr.strip() or proc.stdout.strip() or f"duti rc={proc.returncode}"
                        errs.append((f"uti:{uti}:{role}", msg))
                except Exception as ex:
                    errs.append((f"uti:{uti}:{role}", str(ex)))

        return ok, errs

    def _default_file_association_exts(self) -> list[str]:
        """Vom Editor sinnvoll unterstützte bzw. oft gewünschte Verknüpfungen."""
        return [
            ".txt",
            ".md",
            ".markdown",
            ".yaml",
            ".yml",
            ".rs",
            ".js",
            ".mjs",
            ".cjs",
            ".java",
            ".bat",
            ".cmd",
            ".ps1",
            ".html",
            ".htm",
            ".css",
            ".php",
            ".py",
            ".tex",
            ".sh",
            ".command",
            ".json",
            ".log",
        ]

    def _utis_for_file_association_exts(self, exts) -> list[tuple[str, str]]:
        normalized = {
            f".{str(ext).lstrip('.').lower()}"
            for ext in (exts or [])
            if str(ext).strip()
        }
        utis = []
        if normalized & {".txt", ".log"}:
            utis.append(("public.plain-text", "editor"))
        if normalized & {".md", ".markdown"}:
            utis.append(("net.daringfireball.markdown", "editor"))
        if ".json" in normalized:
            utis.append(("public.json", "editor"))
        if normalized & {".html", ".htm"}:
            utis.append(("public.html", "editor"))
        if ".css" in normalized:
            utis.append(("public.css", "editor"))
        if ".py" in normalized:
            utis.append(("public.python-script", "editor"))
        if ".tex" in normalized:
            utis.append(("public.tex", "editor"))
        return utis

    def _apply_default_associations(self):
        """
        Verlinkt gängige Text-/Code-Formate auf MAAT Notepad.
        Extensions + UTIs (für .py besonders wichtig).
        """
        exts = self._default_file_association_exts()
        utis = self._utis_for_file_association_exts(exts)
        return self._apply_file_assoc_with_duti(exts=exts, utis=utis)


    # --- UI ---
    def _build_menu(self):
        menubar = tk.Menu(self)

        # Datei
        filem = tk.Menu(menubar, tearoff=0)
        self._safe_add_command(filem, label="Neu",                 command=self._new_note,      accelerator="Cmd+N")
        self._safe_add_command(filem, label="Neuer Tab",           command=self._new_tab,       accelerator="Cmd+T")
        self._safe_add_command(filem, label="Tab schließen",       command=self._close_active_tab, accelerator="Cmd+W")
        filem.add_separator()
        self._safe_add_command(filem, label="Öffnen…",             command=self._open_file,     accelerator="Cmd+O")
        self._safe_add_command(filem, label="Einfügen aus Datei…", command=self._insert_file)
        self._safe_add_command(filem, label="TeX-Anhang einfügen…", command=self._insert_tex_attachment)
        self._safe_add_command(filem, label="Speichern",           command=self._on_save_click, accelerator="Cmd+S")
        self._safe_add_command(filem, label="Speichern unter…",    command=self._save_as_file)
        filem.add_separator()
        self._safe_add_command(filem, label="Export JSON…",        command=self._export_json)
        self._safe_add_command(filem, label="Import JSON…",        command=self._import_json)
        filem.add_separator()
        self._safe_add_command(filem, label="Beenden",             command=self._on_close)
        menubar.add_cascade(label="Datei", menu=filem)

        # Ansicht
        viewm = tk.Menu(menubar, tearoff=0)
        self._safe_add_command(viewm, label="Alle zeigen", command=lambda: self._set_filter(None))
        for p in PRINCIPLES:
            self._safe_add_command(viewm, label=f"Filter: {p}", command=lambda n=p: self._set_filter(n))
        sortm = tk.Menu(viewm, tearoff=0)
        for mode, label in NOTE_SORT_CHOICES:
            self._safe_add_radiobutton(
                sortm,
                label=label,
                variable=self.note_sort_mode_var,
                value=mode,
                command=lambda m=mode: self._set_note_sort_mode(m),
            )
        self._safe_add_cascade(viewm, label="Sortierung", menu=sortm)
        menubar.add_cascade(label="Ansicht", menu=viewm)

        # Prinzipien
        princm = tk.Menu(menubar, tearoff=0)
        self._safe_add_command(princm, label="Filter wählen…", command=self._choose_principle)
        menubar.add_cascade(label="Prinzipien", menu=princm)

        # Suchen
        searchm = tk.Menu(menubar, tearoff=0)
        self._safe_add_command(searchm, label="Suchen…",               command=self._open_find,    accelerator="Cmd+F")
        self._safe_add_command(searchm, label="Ersetzen…",             command=self._open_replace, accelerator="Cmd+H")
        searchm.add_separator()
        self._safe_add_command(searchm, label="Nächstes Vorkommen",    command=self._find_next,    accelerator="Cmd+G")
        self._safe_add_command(searchm, label="Vorheriges Vorkommen",  command=self._find_prev,    accelerator="Shift+Cmd+G")
        menubar.add_cascade(label="Suchen", menu=searchm)
        
        # --- Format ---
        formatm = tk.Menu(menubar, tearoff=0)

        # Feste Einrückung (setzt jede nicht-leere Zeile exakt auf N×4 Spaces)
        formatm.add_command(label="Einrückung entfernen (0 × 4)", accelerator="⌘⌥0",
                            command=lambda: self._reindent(0, scope="auto"))
        formatm.add_command(label="Einrückung: 1 × 4", accelerator="⌘⌥1",
                            command=lambda: self._reindent(1, scope="auto"))
        formatm.add_command(label="Einrückung: 2 × 4", accelerator="⌘⌥2",
                            command=lambda: self._reindent(2, scope="auto"))
        formatm.add_command(label="Einrückung: 3 × 4", accelerator="⌘⌥3",
                            command=lambda: self._reindent(3, scope="auto"))
        formatm.add_command(label="Einrückung: 4 × 4", accelerator="⌘⌥4",
                            command=lambda: self._reindent(4, scope="auto"))

        formatm.add_separator()

        # Relative Ein-/Ausrücken (verschiebt um ±4 Spaces)
        formatm.add_command(label="Einrücken (→ 4)", accelerator="⌘]",
                            command=lambda: self._indent_block(1))
        formatm.add_command(label="Ausrücken (← 4)", accelerator="⌘[",
                            command=lambda: self._dedent_block(1))

        menubar.add_cascade(label="Format", menu=formatm)


        # Einstellungen
        prefs = tk.Menu(menubar, tearoff=0)
        self._safe_add_command(prefs, label="Editor-Schrift…", command=self._open_editor_font_settings, accelerator="Cmd+,")
        prefs.add_separator()
        self._safe_add_command(prefs, label="Schriftgröße größer", command=lambda: self._adjust_editor_font_size(1), accelerator="Cmd++")
        self._safe_add_command(prefs, label="Schriftgröße kleiner", command=lambda: self._adjust_editor_font_size(-1), accelerator="Cmd+-")
        self._safe_add_command(prefs, label="Standard-Schrift wiederherstellen", command=self._reset_editor_font_settings, accelerator="Cmd+0")
        prefs.add_separator()
        self._safe_add_command(prefs, label="Dateiformate verlinken…", command=self._open_file_assoc)
        menubar.add_cascade(label="Einstellungen", menu=prefs)

        # Python / venv
        pym = tk.Menu(menubar, tearoff=0)
        self._safe_add_command(pym, label="venv auswählen…", command=self._choose_python_venv)
        self._safe_add_command(pym, label="venv-Automatik verwenden", command=self._clear_python_interpreter_override)
        pym.add_separator()
        self._safe_add_command(pym, label="venv im Terminal öffnen", command=self._open_venv_in_terminal)
        self._safe_add_command(pym, label="Pfad im Terminal öffnen", command=self._open_path_in_terminal)
        menubar.add_cascade(label="Python", menu=pym)

        # Darstellung
        view_theme = tk.Menu(menubar, tearoff=0)
        view_theme.add_checkbutton(label="Dunkelmodus", variable=self.dark_mode, command=self._toggle_dark_mode)
        view_theme.add_checkbutton(label="Vorschau", variable=self.preview_mode, command=self._toggle_markdown_preview)
        menubar.add_cascade(label="Darstellung", menu=view_theme)

        # Hilfe
        helpm = tk.Menu(menubar, tearoff=0)
        self._safe_add_command(helpm, label="Über…", command=self._about)
        menubar.add_cascade(label="Hilfe", menu=helpm)

        # Menü setzen
        self.config(menu=menubar)

        # Shortcuts (wie gehabt)
        # Datei
        self.bind_all("<Command-n>", lambda e: self._new_note())
        self.bind_all("<Command-o>", lambda e: self._open_file())
        self.bind_all("<Command-s>", lambda e: self._on_save_click())
        self.bind_all("<Command-t>", lambda e: self._new_tab())
        self.bind_all("<Command-w>", lambda e: self._close_active_tab())

        # Pane-Fokus (Listbox / Titel / Editor)
        self.bind_all("<Command-1>", lambda e: self._nav_open())
        self.bind_all("<Command-2>", lambda e: self.title_entry.focus_set() if hasattr(self, "title_entry") else None)
        self.bind_all("<Command-3>", lambda e: self.text.focus_set() if hasattr(self, "text") else None)
        self.bind_all("<Command-comma>", lambda e: self._open_editor_font_settings())
        self.bind_all("<Command-Shift-M>", lambda e: self._flip_markdown_preview())
        self.bind_all("<Command-Shift-m>", lambda e: self._flip_markdown_preview())
        self.bind_all("<Command-plus>", lambda e: self._adjust_editor_font_size(1))
        self.bind_all("<Command-KP_Add>", lambda e: self._adjust_editor_font_size(1))
        self.bind_all("<Command-equal>", lambda e: self._adjust_editor_font_size(1))
        self.bind_all("<Command-minus>", lambda e: self._adjust_editor_font_size(-1))
        self.bind_all("<Command-KP_Subtract>", lambda e: self._adjust_editor_font_size(-1))
        self.bind_all("<Command-0>", lambda e: self._reset_editor_font_settings())

        # Suchen
        self.bind_all("<Command-f>",       lambda e: self._open_find())
        self.bind_all("<Command-Alt-f>",   lambda e: self._open_replace())   # statt Cmd+H (Systemkonflikt)
        self.bind_all("<Command-g>",       lambda e: self._find_next())
        self.bind_all("<Shift-Command-g>", lambda e: self._find_prev())

        # Feste Einrückung: Auswahl → sonst ganzes Dokument
        self.bind_all("<Command-Option-0>", lambda e: self._reindent(0, "auto"))
        self.bind_all("<Command-Option-1>", lambda e: self._reindent(1, "auto"))
        self.bind_all("<Command-Option-2>", lambda e: self._reindent(2, "auto"))
        self.bind_all("<Command-Option-3>", lambda e: self._reindent(3, "auto"))
        self.bind_all("<Command-Option-4>", lambda e: self._reindent(4, "auto"))

        # Relativ (macOS-typisch: Cmd+[ / Cmd+])
        self.bind_all("<Command-bracketright>", lambda e: self._indent_block(1))
        self.bind_all("<Command-bracketleft>",  lambda e: self._dedent_block(1))

    # --- Theme helpers ---
    def _palette(self):
        c = self._base_palette()
        if self.dark_mode.get():
            c.update(bg="#111718", panel="#192123", sunken="#151C1E",
                     border="#303D40", fg="#E5EEEA", muted="#A2B3B0",
                     accent="#86CFB2", listbg="#141C1E", listfg="#CAD8D3",
                     gutter="#192123", gutterfg="#7F9690", toolbar="#141C1E",
                     selbg="#31584F", selfg="#F1FCF7", cursor="#A6E7CB",
                     current="#21312F", current_no_bg="#29433B", current_no_fg="#A6E7CB",
                     codebg="#23302E", btn_bg="#263335", btn_fg="#E5EEEA",
                     btn_hover="#334547", btn_pressed="#3A5550", btn_border="#303D40",
                     btn_subtle_bg="#192123", btn_subtle_hover="#263735",
                     btn_subtle_pressed="#304940", btn_muted_fg="#A2B3B0",
                     brace_match_bg="#31584F", brace_error_bg="#542D32")
        else:
            c.update(bg="#E9EDE6", panel="#FAFBF6", sunken="#F2F5EE",
                     border="#C8D2C9", fg="#23392F", muted="#596F64",
                     accent="#276A50", listbg="#EEF2EB", listfg="#304A3D",
                     gutter="#FAFBF6", gutterfg="#6D8074", toolbar="#E9EDE6",
                     selbg="#C8E5D6", selfg="#19372A", cursor="#276A50",
                     current="#EAF2E8", current_no_bg="#D6E9DB", current_no_fg="#276A50",
                     codebg="#EAF0E6", btn_bg="#E4ECE2", btn_fg="#23392F",
                     btn_hover="#D4E3D5", btn_pressed="#C4DCCA", btn_border="#C8D2C9",
                     btn_subtle_bg="#F2F5EE", btn_subtle_hover="#E0EADF",
                     btn_subtle_pressed="#D2E2D4", btn_muted_fg="#596F64")
        return c

    def _ui_font(self, size=12, weight="normal"):
        if not getattr(self, "_ui_font_family", None):
            families = set(tkfont.families(self))
            self._ui_font_family = next(
                (name for name in ("Avenir Next", "Avenir", "Helvetica Neue") if name in families),
                tkfont.nametofont("TkDefaultFont").actual("family"),
            )
        return (self._ui_font_family, size, weight)

    def _apply_design_details(self, c):
        """Shared finishing styles for native Tk and themed controls."""
        style = ttk.Style(self)
        for name in ("TButton", "TMenubutton", "Toolbutton"):
            style.configure(name, font=self._ui_font(11), padding=(12, 5), borderwidth=0)
        style.configure("Accent.TButton", background=c["accent"], foreground=c["bg"],
                        font=self._ui_font(11, "bold"), borderwidth=0)
        style.map("Accent.TButton", background=[("disabled", c["btn_bg"]), ("active", c["current_no_fg"])],
                  foreground=[("disabled", c["muted"]), ("!disabled", c["bg"])])
        style.configure("TPanedwindow", background=c["bg"])
        style.configure("Sash", sashthickness=6, background=c["bg"])
        for name in ("Horizontal.TScrollbar", "Vertical.TScrollbar", "Tabs.Horizontal.TScrollbar"):
            style.configure(name, background=c["border"], troughcolor=c["panel"],
                            bordercolor=c["panel"], lightcolor=c["panel"], darkcolor=c["panel"],
                            arrowcolor=c["muted"], borderwidth=0, arrowsize=10)
            style.map(name, background=[("active", c["muted"]), ("pressed", c["accent"])])
        style.configure("Tabs.Horizontal.TScrollbar", arrowsize=7, troughcolor=c["toolbar"])
        for widget in (getattr(self, "search_entry", None), getattr(self, "title_entry", None),
                       getattr(self, "quickfind_entry", None)):
            if widget:
                widget.configure(bd=0, relief="flat", highlightthickness=1,
                                 highlightbackground=c["border"], highlightcolor=c["accent"],
                                 font=self._ui_font(12))
        for name in ("library_heading", "library_subheading"):
            widget = getattr(self, name, None)
            if widget:
                widget.configure(bg=c["listbg"], fg=c["accent"] if name == "library_heading" else c["muted"])
        if getattr(self, "filter_hint", None):
            self.filter_hint.configure(fg=c["muted"], font=self._ui_font(10), anchor="w", justify="left", wraplength=250)
        if getattr(self, "linenos", None):
            self.linenos.configure(spacing1=1, spacing3=1)
        if getattr(self, "tab_canvas", None):
            self.tab_canvas.configure(bg=c["toolbar"])
        for doc in getattr(self, "_doc_tabs", []):
            active = bool(doc.get("_tab_active"))
            bg = c["panel"] if active else c["toolbar"]
            for key in ("_tab_frame", "_tab_button", "_tab_close_button"):
                widget = doc.get(key)
                if widget and widget.winfo_exists():
                    widget.configure(bg=bg, highlightthickness=0)
                    if key != "_tab_frame":
                        widget.configure(fg=c["fg"] if active else c["muted"],
                                         font=self._ui_font(11, "bold" if active else "normal"))
            indicator = doc.get("_tab_indicator")
            if indicator and indicator.winfo_exists():
                indicator.configure(bg=c["accent"] if active else c["toolbar"])
        if getattr(self, "new_tab_btn", None):
            self.new_tab_btn.configure(font=self._ui_font(16), highlightthickness=0, bg=c["toolbar"], fg=c["accent"])
        accents = ("#90C9B6", "#BCC8AF", "#D7B58A", "#91BEC7", "#B7BBDD") if self.dark_mode.get() else ("#326D55", "#5C7046", "#89602C", "#326778", "#605B84")
        for index, box in enumerate(getattr(self, "_score_boxes", [])):
            box["frame"].configure(bg=c["sunken"], padx=8, pady=5)
            box["name"].configure(bg=c["sunken"], fg=accents[index % len(accents)], font=self._ui_font(10))
            box["value"].configure(bg=c["sunken"], fg=c["fg"], font=("Menlo", 14))
        if getattr(self, "maat_summary", None):
            self.maat_summary.configure(bg=c["panel"], fg=c["accent"])
        if getattr(self, "status_label", None):
            self.status_label.configure(bg=c["bg"], fg=c["muted"], font=self._ui_font(10), padx=14, pady=5)
            self.status_wrap.configure(bg=c["bg"])

    def _base_palette(self):
        if self.dark_mode.get():
            return {
                "bg":       "#0F1115",
                "panel":    "#161A22",
                "sunken":   "#1B2130",
                "border":   "#2A3140",
                "fg":       "#E6EDF3",
                "muted":    "#9AA4B2",
                "accent":   "#58A6FF",
                "listbg":   "#11161F",
                "listfg":   "#D6DEEB",
                "gutter":   "#0D121A",
                "gutterfg": "#6F7B8A",
                "selbg":    "#243B53",
                "selfg":    "#FFFFFF",
                "cursor":   "#FFFFFF",
                "find_all": "#5C4500",
                "find_cur": "#7C5C00",
                "toolbar":  "#121722",
                "current":  "#1C2533",
                "current_no_bg": "#1E2F45",
                "current_no_fg": "#8FC7FF",
                "brace_match_bg": "#243B53",
                "brace_error_bg": "#4A2328",
                "codebg":   "#1B2330",
                "badge_fg": "#F4F8FF",
                "btn_bg":   "#202938",
                "btn_fg":   "#EAF2FF",
                "btn_hover": "#2A3649",
                "btn_pressed": "#32425C",
                "btn_border": "#3A4B63",
                "btn_subtle_bg": "#161D28",
                "btn_subtle_hover": "#202A39",
                "btn_subtle_pressed": "#293548",
                "btn_muted_fg": "#B8C3D3",
            }
        else:
            return {
                "bg":       "#EEF2F7",
                "panel":    "#FBFCFE",
                "sunken":   "#FFFFFF",
                "border":   "#D7DDE7",
                "fg":       "#17212B",
                "muted":    "#586271",
                "accent":   "#0F6CBD",
                "listbg":   "#E8EDF4",
                "listfg":   "#17212B",
                "gutter":   "#F2F5FA",
                "gutterfg": "#7B8794",
                "selbg":    "#CCE2FF",
                "selfg":    "#000000",
                "cursor":   "#000000",
                "find_all": "#FFE08A",
                "find_cur": "#FFEFA6",
                "toolbar":  "#F4F7FB",
                "current":  "#EEF4FF",
                "current_no_bg": "#DCEBFF",
                "current_no_fg": "#0F4C81",
                "brace_match_bg": "#CFE8FF",
                "brace_error_bg": "#FFCDD2",
                "codebg":   "#F6F9FC",
                "badge_fg": "#FFFFFF",
                "btn_bg":   "#FFFFFF",
                "btn_fg":   "#17212B",
                "btn_hover": "#EEF4FF",
                "btn_pressed": "#DCEBFF",
                "btn_border": "#C7D2E2",
                "btn_subtle_bg": "#F4F7FB",
                "btn_subtle_hover": "#E8EFFA",
                "btn_subtle_pressed": "#DAE7F7",
                "btn_muted_fg": "#586271",
            }

    def _normalize_note_sort_mode(self, mode):
        mode = str(mode or "").strip().lower()
        valid = {item[0] for item in NOTE_SORT_CHOICES}
        return mode if mode in valid else DEFAULT_NOTE_SORT_MODE

    def _note_sort_label(self, mode=None):
        mode = self._normalize_note_sort_mode(mode or self.note_sort_mode_var.get())
        for key, label in NOTE_SORT_CHOICES:
            if key == mode:
                return label
        return NOTE_SORT_CHOICES[0][1]

    def _sorted_notes(self, notes):
        items = list(notes or [])
        mode = self._normalize_note_sort_mode(self.note_sort_mode_var.get())

        def _text_key(value):
            return str(value or "").casefold()

        def _float_key(value):
            try:
                return float(value or 0.0)
            except Exception:
                return 0.0

        def _date_key(note, field):
            raw = note.get(field) or ""
            return str(raw)

        reverse = False
        if mode == "updated_desc":
            reverse = True
            keyfunc = lambda note: (_date_key(note, "updated"), note.get("id", 0))
        elif mode == "updated_asc":
            keyfunc = lambda note: (_date_key(note, "updated"), note.get("id", 0))
        elif mode == "created_desc":
            reverse = True
            keyfunc = lambda note: (_date_key(note, "created"), note.get("id", 0))
        elif mode == "created_asc":
            keyfunc = lambda note: (_date_key(note, "created"), note.get("id", 0))
        elif mode == "title_desc":
            reverse = True
            keyfunc = lambda note: (_text_key(note.get("title")), note.get("id", 0))
        elif mode == "title_asc":
            keyfunc = lambda note: (_text_key(note.get("title")), note.get("id", 0))
        elif mode == "maat_desc":
            reverse = True
            keyfunc = lambda note: (_float_key(note.get("maat")), _text_key(note.get("title")))
        elif mode == "maat_asc":
            keyfunc = lambda note: (_float_key(note.get("maat")), _text_key(note.get("title")))
        else:
            keyfunc = lambda note: (_date_key(note, "updated"), note.get("id", 0))
            reverse = True

        try:
            return sorted(items, key=keyfunc, reverse=reverse)
        except Exception:
            return items

    def _capture_window_settings(self):
        try:
            geometry = str(self.winfo_geometry() or self.geometry() or DEFAULT_WINDOW_GEOMETRY)
        except Exception:
            geometry = str(self.ui_state.get("window_geometry", DEFAULT_WINDOW_GEOMETRY))
        try:
            window_state = str(self.state() or "normal")
        except Exception:
            window_state = str(self.ui_state.get("window_state", "normal"))
        if window_state in {"iconic", "withdrawn"}:
            window_state = "normal"
        try:
            nav_open = self.root_split.sashpos(0) >= 80
        except Exception:
            nav_open = bool(self.ui_state.get("nav_open", False))
        return geometry, window_state, bool(nav_open)

    def _persist_main_ui_state(self, *, root_sash=None, right_sash=None):
        # Modal startup dialogs process Tk events before a session has been chosen.
        if getattr(self, "_restoring_tab_session", False):
            return
        try:
            self._session_persist_after = None
        except Exception:
            pass
        try:
            if root_sash is None or right_sash is None:
                root_sash, right_sash = self._capture_sashes()
        except Exception:
            root_sash = int(self.ui_state.get("root_sash", 320))
            right_sash = int(self.ui_state.get("right_sash", 460))

        try:
            self._sync_active_tab_from_editor(schedule=False, rebuild=False)
        except Exception:
            pass

        geometry, window_state, nav_open = self._capture_window_settings()

        try:
            self.ui_state["dark_mode"] = bool(self.dark_mode.get())
            self.ui_state["markdown_preview"] = bool(self.preview_mode.get())
            self.ui_state["editor_font_family"] = self._sanitize_editor_font_family(self.editor_font_family)
            self.ui_state["editor_font_size"] = self._sanitize_editor_font_size(self.editor_font_size)
            self.ui_state["root_sash"] = int(root_sash)
            self.ui_state["right_sash"] = int(right_sash)
            self.ui_state["nav_open"] = bool(nav_open)
            self.ui_state["window_geometry"] = geometry
            self.ui_state["window_state"] = window_state
            self.ui_state["note_sort_mode"] = self._normalize_note_sort_mode(self.note_sort_mode_var.get())
            self.ui_state["open_tabs"] = [self._serialize_tab_session(doc) for doc in self._doc_tabs]
            self.ui_state["active_tab_index"] = max(0, int(self._active_tab_index))

            _atomic_write_json(UI_STATE_FILE, self.ui_state)
            return True
        except Exception as exc:
            self.status_message(f"Sitzung konnte nicht gespeichert werden: {exc}")
            return False

    def _restore_window_settings(self):
        try:
            geometry = str(self.ui_state.get("window_geometry", DEFAULT_WINDOW_GEOMETRY) or DEFAULT_WINDOW_GEOMETRY)
            if geometry:
                self.geometry(geometry)
        except Exception:
            pass

        state = str(self.ui_state.get("window_state", "normal") or "normal").lower()
        if state == "zoomed":
            try:
                self.state("zoomed")
            except Exception:
                pass

    def _update_filter_hint(self):
        try:
            if not getattr(self, "filter_hint", None):
                return
            filt = self.filter_principle or "Alle"
            count = len(self._filtered_notes())
            self.filter_hint.configure(
                text=f"{count} Notizen  ·  {filt}\n{self._note_sort_label()}"
            )
        except Exception:
            pass

    def _set_note_sort_mode(self, mode):
        normalized = self._normalize_note_sort_mode(mode)
        try:
            self.note_sort_mode_var.set(normalized)
        except Exception:
            pass
        self._refresh_list()
        self._persist_main_ui_state()
        self.status_message(f"Sortierung: {self._note_sort_label(normalized)}")

    def _next_tab_id(self):
        value = int(getattr(self, "_next_tab_serial", 1))
        self._next_tab_serial = value + 1
        return f"tab-{value}"

    def _read_text_file_with_fallback(self, path):
        p = Path(path)
        last_error = None
        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                return p.read_text(encoding=enc)
            except Exception as e:
                last_error = e
        raise last_error or RuntimeError(f"Konnte Datei nicht lesen: {path}")

    def _tab_label_for_document(self, doc):
        if not isinstance(doc, dict):
            return "Tab"
        external_path = doc.get("external_file")
        if external_path:
            base = Path(external_path).name
        else:
            base = str(doc.get("title") or "").strip() or "Neue Notiz"
        if doc.get("dirty"):
            base += " *"
        return base

    def _make_tab_document(
        self,
        *,
        title="",
        content="",
        current_id=None,
        external_file=None,
        scores=None,
        maat=None,
        dirty=False,
        code_mode=None,
        cursor_index="1.0",
        yview=0.0,
        tab_id=None,
    ):
        external_path = str(external_file) if external_file else None
        if code_mode is None:
            code_mode = self._is_code_file_path(external_path) if external_path else False
        try:
            yview = float(yview)
        except Exception:
            yview = 0.0
        return {
            "tab_id": tab_id or self._next_tab_id(),
            "title": str(title or "").strip(),
            "content": str(content or ""),
            "current_id": current_id,
            "external_file": external_path,
            "scores": dict(scores) if isinstance(scores, dict) else None,
            "maat": float(maat) if maat is not None else None,
            "dirty": bool(dirty),
            "code_mode": bool(code_mode),
            "cursor_index": str(cursor_index or "1.0"),
            "yview": max(0.0, min(1.0, yview)),
        }

    def _blank_tab_document(self):
        return self._make_tab_document(title="", content="", current_id=None, external_file=None, scores=None, maat=None, dirty=False, code_mode=False)

    def _note_to_tab_document(self, note):
        note = dict(note or {})
        return self._make_tab_document(
            title=note.get("title", ""),
            content=note.get("content", ""),
            current_id=note.get("id"),
            external_file=None,
            scores=note.get("scores"),
            maat=note.get("maat"),
            dirty=False,
            code_mode=False,
        )

    def _external_to_tab_document(self, path, content=None):
        if content is None:
            content = self._read_text_file_with_fallback(path)
        p = Path(path)
        return self._make_tab_document(
            title=p.stem,
            content=content,
            current_id=None,
            external_file=str(p),
            scores=None,
            maat=None,
            dirty=False,
            code_mode=self._is_code_file_path(str(p)),
        )

    def _current_tab_doc(self):
        if 0 <= self._active_tab_index < len(self._doc_tabs):
            return self._doc_tabs[self._active_tab_index]
        return None

    def _is_blank_tab_doc(self, doc):
        if not isinstance(doc, dict):
            return False
        return (
            not doc.get("current_id")
            and not doc.get("external_file")
            and not str(doc.get("title") or "").strip()
            and not str(doc.get("content") or "").strip()
            and not bool(doc.get("dirty"))
        )

    def _find_tab_by_external_path(self, path):
        if not path:
            return None
        needle = str(Path(path))
        for idx, doc in enumerate(self._doc_tabs):
            if str(doc.get("external_file") or "") == needle:
                return idx
        return None

    def _find_tab_by_note_id(self, note_id):
        if note_id is None:
            return None
        for idx, doc in enumerate(self._doc_tabs):
            if doc.get("current_id") == note_id and not doc.get("external_file"):
                return idx
        return None

    def _find_note_by_id(self, note_id):
        if note_id is None:
            return None
        for note in self.notes:
            if note.get("id") == note_id:
                return note
        return None

    def _current_score_snapshot(self):
        try:
            scores = {}
            for principle in PRINCIPLES:
                raw = self.score_labels[principle].get()
                if raw in {"", "–"}:
                    return None, None
                scores[principle] = float(str(raw).replace(",", "."))
            maat_raw = str(self.maat_var.get() or "").replace("MAAT:", "").strip()
            maat = float(maat_raw.replace(",", ".")) if maat_raw and maat_raw != "–" else None
            return scores, maat
        except Exception:
            return None, None

    def _sync_active_tab_from_editor(self, *, schedule=True, rebuild=True):
        if getattr(self, "_loading_tab_state", False):
            return
        doc = self._current_tab_doc()
        if doc is None or not getattr(self, "text", None):
            return
        try:
            doc["title"] = str((self.title_var.get() or "")).strip()
        except Exception:
            pass
        try:
            doc["content"] = self.text.get("1.0", "end-1c")
        except Exception:
            pass
        doc["current_id"] = self.current_id
        doc["external_file"] = self.external_file
        doc["dirty"] = bool(self._dirty)
        try:
            doc["code_mode"] = bool(self.code_mode.get())
        except Exception:
            pass
        try:
            doc["cursor_index"] = self.text.index("insert")
        except Exception:
            doc["cursor_index"] = "1.0"
        try:
            doc["yview"] = float(self.text.yview()[0])
        except Exception:
            doc["yview"] = 0.0
        scores, maat = self._current_score_snapshot()
        doc["scores"] = dict(scores) if isinstance(scores, dict) else None
        doc["maat"] = maat
        if rebuild:
            self._rebuild_tab_bar()
        if schedule:
            self._schedule_session_persist()

    def _revert_active_document(self):
        doc = self._current_tab_doc()
        if doc is None:
            return

        replacement = None
        external_path = doc.get("external_file")
        note_id = doc.get("current_id")

        if external_path:
            try:
                replacement = self._external_to_tab_document(external_path)
            except Exception as exc:
                messagebox.showerror("Verwerfen", f"Gespeicherte Datei konnte nicht geladen werden:\n{exc}")
                return False
        elif note_id is not None:
            note = self._find_note_by_id(note_id)
            if note is not None:
                replacement = self._note_to_tab_document(note)

        if replacement is None:
            replacement = self._blank_tab_document()

        replacement["tab_id"] = doc.get("tab_id") or replacement.get("tab_id")
        self._doc_tabs[self._active_tab_index] = replacement
        self._load_tab_into_editor(replacement)
        self._rebuild_tab_bar()
        return True

    def _load_tab_into_editor(self, doc):
        doc = dict(doc or {})
        self._loading_tab_state = True
        try:
            self.current_id = doc.get("current_id")
            self.external_file = doc.get("external_file")
            self.title_var.set(doc.get("title", ""))
            self.text.delete("1.0", "end")
            self.text.insert("1.0", doc.get("content", ""))
            self._set_scores(doc.get("scores"), doc.get("maat"))
            self._dirty = bool(doc.get("dirty"))
            self.code_mode.set(bool(doc.get("code_mode", False)))
            try:
                self.text.edit_reset()
            except Exception:
                pass
            try:
                self.text.edit_modified(False)
            except Exception:
                pass
        finally:
            self._loading_tab_state = False

        try:
            self._sync_editor_mode_state()
        except Exception:
            pass
        try:
            self._refresh_run_interpreter()
        except Exception:
            pass
        self._update_header_buttons()
        self._update_linenumbers()
        self._schedule_highlight()
        try:
            self._highlight_current_line()
        except Exception:
            pass
        try:
            self.text.mark_set("insert", doc.get("cursor_index", "1.0"))
        except Exception:
            pass
        try:
            self.text.see(doc.get("cursor_index", "1.0"))
        except Exception:
            pass
        try:
            self.text.yview_moveto(float(doc.get("yview", 0.0)))
        except Exception:
            pass
        self._update_title()
        self._update_statusbar()
        self._refresh_list()

    def _activate_tab(self, index, *, force=False, persist=True):
        if not (0 <= index < len(self._doc_tabs)):
            return False
        if self._active_tab_index == index and not force:
            return True
        if self._active_tab_index >= 0 and not force:
            self._sync_active_tab_from_editor(schedule=False, rebuild=False)
        self._active_tab_index = int(index)
        self._load_tab_into_editor(self._doc_tabs[self._active_tab_index])
        self._rebuild_tab_bar()
        if persist:
            self._persist_main_ui_state()
        return True

    def _replace_active_tab(self, doc, *, persist=True):
        if not self._doc_tabs:
            self._doc_tabs = [doc]
            self._active_tab_index = 0
        else:
            self._doc_tabs[self._active_tab_index] = doc
        self._activate_tab(self._active_tab_index, force=True, persist=persist)

    def _open_document_in_tab(self, doc, *, reuse_blank=True, persist=True):
        self._sync_active_tab_from_editor(schedule=False, rebuild=False)
        if reuse_blank and self._is_blank_tab_doc(self._current_tab_doc()):
            self._replace_active_tab(doc, persist=persist)
            return
        self._doc_tabs.append(doc)
        self._activate_tab(len(self._doc_tabs) - 1, force=True, persist=persist)

    def _on_tab_click(self, index):
        self._activate_tab(index)

    def _close_tab(self, index=None):
        if not self._doc_tabs:
            return
        if index is None:
            index = self._active_tab_index
        if not (0 <= index < len(self._doc_tabs)):
            return

        if index != self._active_tab_index:
            self._activate_tab(index, persist=False)

        if not self._maybe_close_current():
            return

        try:
            self._sync_active_tab_from_editor(schedule=False, rebuild=False)
        except Exception:
            pass

        self._doc_tabs.pop(self._active_tab_index)
        if not self._doc_tabs:
            self._doc_tabs = [self._blank_tab_document()]
            self._active_tab_index = 0
        else:
            self._active_tab_index = max(0, min(index, len(self._doc_tabs) - 1))
        self._activate_tab(self._active_tab_index, force=True, persist=True)

    def _new_tab(self):
        self._open_document_in_tab(self._blank_tab_document(), reuse_blank=True)
        self.status_message("Neuer Tab geöffnet.")
        return "break"

    def _close_active_tab(self):
        self._close_tab(self._active_tab_index)
        return "break"

    def _select_note_in_new_tab(self, _event=None):
        try:
            if getattr(self, "_note_select_after", None):
                self.after_cancel(self._note_select_after)
                self._note_select_after = None
        except Exception:
            self._note_select_after = None
        idx = self._select_index()
        if idx is None:
            return "break"
        note = self._filtered_notes()[idx]
        existing = self._find_tab_by_note_id(note.get("id"))
        if existing is not None:
            self._activate_tab(existing)
            return "break"
        self._open_document_in_tab(self._note_to_tab_document(note), reuse_blank=True)
        return "break"

    def _rebuild_tab_bar(self):
        if not getattr(self, "tab_inner", None):
            return
        try:
            for child in self.tab_inner.winfo_children():
                child.destroy()
        except Exception:
            return

        active = self._active_tab_index
        for idx, doc in enumerate(self._doc_tabs):
            item = tk.Frame(self.tab_inner, bd=0, highlightthickness=1)
            item.pack(side="left", padx=(0, 4), pady=0)
            indicator = tk.Frame(item, height=2)
            indicator.pack(side="bottom", fill="x")
            label = self._tab_label_for_document(doc)
            if len(label) > 28:
                label = label[:24] + "…" + (" *" if doc.get("dirty") else "")
            btn = tk.Label(
                item,
                text=label,
                relief="flat",
                bd=0,
                padx=10,
                pady=8,
                anchor="w",
                cursor="hand2",
            )
            btn.pack(side="left")
            item.bind("<ButtonRelease-1>", lambda _e, i=idx: self._on_tab_click(i))
            btn.bind("<ButtonRelease-1>", lambda _e, i=idx: self._on_tab_click(i))
            close_btn = tk.Label(
                item,
                text="×",
                relief="flat",
                bd=0,
                padx=6,
                pady=5,
                cursor="hand2",
            )
            close_btn.pack(side="left")
            close_btn.bind("<ButtonRelease-1>", lambda _e, i=idx: self._close_tab(i))
            doc["_tab_frame"] = item
            doc["_tab_indicator"] = indicator
            doc["_tab_button"] = btn
            doc["_tab_close_button"] = close_btn
            doc["_tab_active"] = idx == active

        self._apply_theme()
        if getattr(self, "tab_canvas", None):
            self.after_idle(self._reveal_active_tab)

    def _reveal_active_tab(self):
        doc = self._current_tab_doc()
        if not doc or not getattr(self, "tab_canvas", None):
            return
        frame = doc.get("_tab_frame")
        if not frame or not frame.winfo_exists():
            return
        bounds = self.tab_canvas.bbox("all")
        if not bounds:
            return
        self.tab_canvas.configure(scrollregion=bounds)
        total = max(1, bounds[2])
        left = self.tab_canvas.canvasx(0)
        width = self.tab_canvas.winfo_width()
        start = frame.winfo_x()
        end = start + frame.winfo_width()
        if start < left:
            self.tab_canvas.xview_moveto(start / total)
        elif end > left + width:
            self.tab_canvas.xview_moveto(max(0, end - width) / total)

    def _on_tab_strip_resize(self, _event=None):
        self.tab_canvas.configure(scrollregion=self.tab_canvas.bbox("all"))
        # Child geometry is finalized after the container's Configure event.
        self.after_idle(self._reveal_active_tab)

    def _serialize_tab_session(self, doc):
        payload = self._make_tab_document(
            title=doc.get("title", ""),
            content=doc.get("content", ""),
            current_id=doc.get("current_id"),
            external_file=doc.get("external_file"),
            scores=doc.get("scores"),
            maat=doc.get("maat"),
            dirty=doc.get("dirty"),
            code_mode=doc.get("code_mode"),
            cursor_index=doc.get("cursor_index", "1.0"),
            yview=doc.get("yview", 0.0),
            tab_id=doc.get("tab_id"),
        )
        return payload

    def _restore_tab_session(self):
        docs = []
        raw_tabs = self.ui_state.get("open_tabs", [])
        if not isinstance(raw_tabs, list):
            raw_tabs = []
        try:
            saved_active = int(self.ui_state.get("active_tab_index", 0) or 0)
        except (ValueError, TypeError):
            saved_active = 0
        indexed_tabs = [
            (index, item) for index, item in enumerate(raw_tabs)
            if isinstance(item, dict) and not self._is_blank_tab_doc(item)
        ]
        active_index = 0
        if indexed_tabs:
            count = len(indexed_tabs)
            dirty_count = sum(bool(item.get("dirty")) for _, item in indexed_tabs)
            limit = 20
            detail = (
                f"Letzte Tabs öffnen?\n\n{count} Tabs aus der letzten Sitzung"
                f" ({dirty_count} mit ungespeicherten Änderungen).\n\n"
                "Nein: mit einem leeren Tab starten. Die alte Sitzung wird "
                "zur Sicherheit separat gespeichert."
            )
            if count > limit:
                detail += (
                    f"\n\nZum Schutz vor einem überlasteten Start werden höchstens {limit} "
                    "Tabs geöffnet (der zuletzt aktive und die letzten Tabs). "
                    "Die vollständige Sitzung bleibt als Sicherung erhalten."
                )
            restore = messagebox.askyesno(
                "Letzte Sitzung", detail, parent=self, default=messagebox.NO,
            )
            if not restore or count > limit:
                self._archive_tab_session(raw_tabs, saved_active)
            if not restore:
                indexed_tabs = []
            elif count > limit:
                selected = indexed_tabs[-limit:]
                active = next((pair for pair in indexed_tabs if pair[0] == saved_active), None)
                if active and all(index != saved_active for index, _ in selected):
                    selected = [active] + selected[-(limit - 1):]
                indexed_tabs = selected
            active_index = next(
                (pos for pos, (index, _) in enumerate(indexed_tabs) if index == saved_active), 0,
            )
        raw_tabs = [item for _, item in indexed_tabs]
        if isinstance(raw_tabs, list):
            for item in raw_tabs:
                if not isinstance(item, dict):
                    continue
                external_path = item.get("external_file")
                content = item.get("content", "")
                if external_path and os.path.exists(external_path) and not item.get("dirty"):
                    try:
                        content = self._read_text_file_with_fallback(external_path)
                    except Exception:
                        pass
                docs.append(
                    self._make_tab_document(
                        title=item.get("title", ""),
                        content=content,
                        current_id=item.get("current_id"),
                        external_file=external_path,
                        scores=item.get("scores"),
                        maat=item.get("maat"),
                        dirty=item.get("dirty", False),
                        code_mode=item.get("code_mode", self._is_code_file_path(external_path) if external_path else False),
                        cursor_index=item.get("cursor_index", "1.0"),
                        yview=item.get("yview", 0.0),
                        tab_id=item.get("tab_id"),
                    )
                )

        if not docs:
            docs = [self._blank_tab_document()]

        self._doc_tabs = docs
        self._next_tab_serial = max(
            [self._next_tab_serial]
            + [int(str(doc.get("tab_id", "tab-0")).split("-")[-1]) + 1 for doc in docs if str(doc.get("tab_id", "")).startswith("tab-") and str(doc.get("tab_id", "")).split("-")[-1].isdigit()]
        )
        active_index = max(0, min(active_index, len(self._doc_tabs) - 1))
        self._active_tab_index = -1
        self._activate_tab(active_index, force=True, persist=False)

    def _archive_tab_session(self, tabs, active_index):
        """Keep skipped drafts outside the next automatically saved session."""
        payload = {"open_tabs": tabs, "active_tab_index": active_index}
        try:
            folder = Path(APP_SUPPORT) / "session_backups"
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix="session-", suffix=".json",
                dir=str(folder), delete=False,
            ) as backup:
                json.dump(payload, backup, ensure_ascii=False, indent=2)
        except Exception as exc:
            # Preserve recovery data in the normal UI state if a separate backup fails.
            key = f"session_recovery_{time.time_ns()}"
            self.ui_state[key] = payload
            messagebox.showwarning(
                "Sitzungssicherung",
                "Die separate Sitzungssicherung konnte nicht geschrieben werden.\n"
                "Die Wiederherstellungsdaten bleiben vorerst in den Einstellungen.\n"
                "Bitte den Speicherort prüfen, bevor du die Anwendung beendest.\n\n"
                f"{exc}", parent=self,
            )

    def _schedule_session_persist(self, delay_ms=900):
        try:
            if getattr(self, "_session_persist_after", None):
                self.after_cancel(self._session_persist_after)
        except Exception:
            pass
        try:
            self._session_persist_after = self.after(delay_ms, self._persist_main_ui_state)
        except Exception:
            pass

    def _available_editor_fonts(self):
        preferred = [
            "Menlo", "SF Mono", "Monaco", "Fira Code", "JetBrains Mono", "Hack",
            "Source Code Pro", "IBM Plex Mono", "Consolas", "Courier New", "Andale Mono",
        ]
        try:
            families = sorted({name.strip() for name in tkfont.families(self) if isinstance(name, str) and name.strip()})
        except Exception:
            families = []

        ordered = [name for name in preferred if name in families]
        remaining = [name for name in families if name not in ordered]
        return ordered + remaining

    def _sanitize_editor_font_family(self, family):
        family = str(family or "").strip()
        available = set(self._available_editor_fonts())
        if family and (not available or family in available):
            return family
        for candidate in ("Menlo", "SF Mono", "Monaco", "Courier New"):
            if not available or candidate in available:
                return candidate
        try:
            return str(tkfont.nametofont("TkFixedFont").cget("family") or "Menlo")
        except Exception:
            return family or "Menlo"

    def _sanitize_editor_font_size(self, size):
        try:
            size = int(size)
        except Exception:
            size = 16
        return max(10, min(36, size))

    def _editor_font(self, size=None, style=None):
        family = self._sanitize_editor_font_family(getattr(self, "editor_font_family", "Menlo"))
        size = self._sanitize_editor_font_size(self.editor_font_size if size is None else size)
        return (family, size, style) if style else (family, size)

    def _editor_heading_font(self, grow_by, minimum):
        size = max(minimum, self._sanitize_editor_font_size(self.editor_font_size + grow_by))
        return self._editor_font(size=size, style="bold")

    def _persist_editor_font_state(self):
        self._persist_main_ui_state()

    def _apply_editor_font_settings(self):
        try:
            self._sync_editor_mode_state()
        except Exception:
            pass
        try:
            self._apply_theme()
        except Exception:
            pass
        try:
            self._update_linenumbers()
            self._highlight_current_line()
            self._sync_gutter_from_text()
        except Exception:
            pass

    def _set_editor_font(self, family=None, size=None, announce=True):
        if family is not None:
            self.editor_font_family = self._sanitize_editor_font_family(family)
        if size is not None:
            self.editor_font_size = self._sanitize_editor_font_size(size)
        self._apply_editor_font_settings()
        self._persist_editor_font_state()
        if announce:
            self.status_message(f"Editor-Schrift: {self.editor_font_family} {self.editor_font_size} pt")
        return "break"

    def _adjust_editor_font_size(self, delta):
        return self._set_editor_font(size=self.editor_font_size + int(delta or 0))

    def _reset_editor_font_settings(self):
        return self._set_editor_font(family="Menlo", size=16)

    def _open_editor_font_settings(self):
        try:
            win = getattr(self, "_editor_font_dialog", None)
            if win and win.winfo_exists():
                win.deiconify()
                win.lift()
                win.focus_force()
                return "break"
        except Exception:
            pass

        win = tk.Toplevel(self)
        self._editor_font_dialog = win
        win.title("Editor-Schrift")
        win.transient(self)
        win.resizable(False, False)

        outer = tk.Frame(win, padx=14, pady=14)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="Schriftart:").grid(row=0, column=0, sticky="w")
        family_var = tk.StringVar(value=self.editor_font_family)
        family_box = ttk.Combobox(
            outer,
            textvariable=family_var,
            values=self._available_editor_fonts(),
            state="readonly",
            width=28,
        )
        family_box.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        tk.Label(outer, text="Schriftgröße:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        size_var = tk.IntVar(value=self.editor_font_size)
        size_spin = tk.Spinbox(outer, from_=10, to=36, textvariable=size_var, width=6)
        size_spin.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(10, 0))

        tk.Label(outer, text="Vorschau:").grid(row=2, column=0, sticky="nw", pady=(12, 0))
        preview = tk.Text(outer, width=34, height=5, wrap="none", padx=10, pady=8, takefocus=0)
        preview.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(12, 0))
        preview.insert("1.0", "def hallo_maat():\n    print('Schrift-Test im Editor')\n")
        preview.configure(state="disabled")

        def refresh_preview(*_args):
            chosen_family = self._sanitize_editor_font_family(family_var.get())
            try:
                chosen_size = self._sanitize_editor_font_size(size_spin.get())
            except Exception:
                chosen_size = self._sanitize_editor_font_size(self.editor_font_size)
            preview.configure(state="normal", font=(chosen_family, chosen_size))
            preview.configure(state="disabled")

        def reset_form():
            family_var.set("Menlo")
            size_var.set(16)
            refresh_preview()

        family_box.bind("<<ComboboxSelected>>", refresh_preview)
        size_spin.bind("<KeyRelease>", refresh_preview)
        size_spin.bind("<ButtonRelease-1>", refresh_preview)
        refresh_preview()

        btns = tk.Frame(outer)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))

        def apply_and_close():
            self._set_editor_font(family=family_var.get(), size=size_var.get())
            try:
                win.destroy()
            except Exception:
                pass

        ttk.Button(btns, text="Standard", command=reset_form).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Abbrechen", command=win.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Übernehmen", command=apply_and_close).pack(side="left")

        outer.columnconfigure(1, weight=1)
        family_box.focus_set()
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Return>", lambda _e: apply_and_close())
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        def _clear_dialog_ref(_event=None):
            if getattr(self, "_editor_font_dialog", None) is win:
                self._editor_font_dialog = None

        win.bind("<Destroy>", _clear_dialog_ref)
        return "break"

    def _toggle_dark_mode(self):
        """Menü-Umschalter."""
        self._apply_theme()
        self._persist_main_ui_state()

#BUILD LAYOUT DESIGN ERSTELLEN
    def _build_layout(self):
        # Root Split: left (search/list) | right (editor+score)
        self.root_split = ttk.Panedwindow(self, orient="horizontal")
        self.root_split.pack(fill="both", expand=True, padx=12, pady=(12, 6))

        # ===== LEFT PANE =====
        left = tk.Frame(self.root_split, bg="#ECECEC", bd=0)
        self.left_pane = left  # für Theme
        self.root_split.add(left, weight=1)

        self.library_heading = tk.Label(left, text="MAAT  /  NOTEPAD", anchor="w", font=self._ui_font(12, "bold"))
        self.library_heading.pack(fill="x", padx=14, pady=(14, 2))
        self.library_subheading = tk.Label(left, text="Dein Raum für Gedanken.", anchor="w", font=self._ui_font(11))
        self.library_subheading.pack(fill="x", padx=14, pady=(0, 22))

        # Search
        sbar = tk.Frame(left, bg="#ECECEC")
        sbar.pack(fill="x", padx=14, pady=(0, 8))
        self.search_bar = sbar  # für Theme
        tk.Label(sbar, text="NOTIZEN DURCHSUCHEN", font=self._ui_font(9, "bold"), bg="#ECECEC").pack(anchor="w", pady=(0, 5))

        self.search_var = tk.StringVar()
        ent = tk.Entry(sbar, textvariable=self.search_var, width=24)
        ent.pack(fill="x", pady=(4, 0))
        self.search_entry = ent  # für Theme

        action_col = tk.Frame(left, bg="#ECECEC")
        action_col.pack(fill="x", padx=14, pady=(0, 12))
        self.search_actions = action_col

        self.search_go_btn = ttk.Button(action_col, text="Suchen", width=10, command=self._refresh_list)
        self.search_go_btn.pack(fill="x")
        self.new_note_btn = ttk.Button(action_col, text="+  Neue Notiz", width=10, command=self._new_note)
        self.new_note_btn.pack(fill="x", pady=(4, 0))
        sort_btn = ttk.Menubutton(action_col, text="Sortieren", width=10)
        sort_menu = tk.Menu(sort_btn, tearoff=0)
        for mode, label in NOTE_SORT_CHOICES:
            sort_menu.add_radiobutton(
                label=label,
                variable=self.note_sort_mode_var,
                value=mode,
                command=lambda m=mode: self._set_note_sort_mode(m),
            )
        sort_btn.configure(menu=sort_menu)
        sort_btn.pack(fill="x", pady=(4, 0))
        self.sort_menu_btn = sort_btn
        self.sort_menu = sort_menu

        hint = tk.Label(left, text="Filter: Alle · Sortierung: Zuletzt geändert: Neu -> Alt", bg="#ECECEC", fg="#444")
        hint.pack(fill="x", padx=14, pady=(0, 10))
        self.filter_hint = hint  # für Theme

        # Listbox
        self.listbox = tk.Listbox(left, width=30, activestyle="none", borderwidth=0,
                                  highlightthickness=0, exportselection=False, font=self._ui_font(12))
        self.listbox.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", self._select_note_in_new_tab)

        # ===== RIGHT SPLIT: editor (top) | score (bottom) =====
        self._right_split = ttk.Panedwindow(self.root_split, orient="vertical")
        self.root_split.add(self._right_split, weight=3)

        right = tk.Frame(self._right_split, bg="#FFFFFF", bd=0, relief="flat", highlightthickness=1)
        self._right_split.add(right, weight=5)
        self.right_pane = right

        self.tab_strip = tk.Frame(right, bg="#F4F7FB")
        self.tab_strip.pack(fill="x", padx=8, pady=(8, 0))
        self.tab_scroll = ttk.Scrollbar(self.tab_strip, orient="horizontal", style="Tabs.Horizontal.TScrollbar")
        self.tab_scroll.pack(side="bottom", fill="x")
        self.new_tab_btn = tk.Label(
            self.tab_strip,
            text="+",
            width=3,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=6,
            pady=5,
        )
        self.new_tab_btn.pack(side="right", padx=(6, 0))
        self.new_tab_btn.bind("<ButtonRelease-1>", lambda _e: self._new_tab())
        self.tab_canvas = tk.Canvas(self.tab_strip, height=40, bd=0, highlightthickness=0,
                                    xscrollcommand=self.tab_scroll.set)
        self.tab_canvas.pack(side="left", fill="x", expand=True)
        self.tab_inner = tk.Frame(self.tab_canvas)
        self.tab_canvas.create_window((0, 0), window=self.tab_inner, anchor="nw")
        self.tab_scroll.configure(command=self.tab_canvas.xview)
        self.tab_inner.bind("<Configure>", self._on_tab_strip_resize)
        self.tab_canvas.bind("<Configure>", self._on_tab_strip_resize)

        # --- Editor top area ---
        title_row = tk.Frame(right, bg="#FFFFFF")
        title_row.pack(fill="x", padx=12, pady=(8, 2))
        self.title_row = title_row  # für Theme

        self.nav_toggle_btn = ttk.Button(title_row, text="☰", width=3, command=self._nav_toggle)
        self.nav_toggle_btn.pack(side="left", padx=(0, 6))
        tk.Label(title_row, text="DOKUMENT", font=self._ui_font(9, "bold"), bg="#FFFFFF").pack(side="left")
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(title_row, textvariable=self.title_var)
        self.title_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.doc_type_badge = tk.Label(title_row, text="NOTE", padx=8, pady=3, font=("Menlo", 11, "bold"))
        self.doc_type_badge.pack(side="right", padx=(0, 6))

        self.save_btn = ttk.Button(title_row, text="Speichern ⌘S", style="Accent.TButton", command=self._on_save_click)
        self.save_btn.pack(side="right")
        self.preview_btn = ttk.Checkbutton(
            title_row,
            text="Vorschau",
            variable=self.preview_mode,
            command=self._toggle_markdown_preview,
            style="Toolbutton",
        )
        self.preview_btn.pack(side="right", padx=6)

        # Zusatz-Button (wird dynamisch ein-/ausgeblendet)
        self.import_btn = ttk.Button(title_row, text="Notiz speichern", command=self._import_external_as_note)
        # NICHT packen – _update_header_buttons() übernimmt das
        self.tex_attach_btn = ttk.Button(title_row, text="TeX-Anhang…", command=self._insert_tex_attachment)
        # NICHT packen – _update_header_buttons() übernimmt das

        # Tooltips
        self._add_tooltip(self.nav_toggle_btn, "Navigation ein-/ausklappen", open_nav_on_click=False)
        self._add_tooltip(self.title_entry, "Titel der Notiz/Datei", open_nav_on_click=False)
        self._add_tooltip(self.save_btn, "Speichert (⌘S)\nKlick auf Tooltip → Navigation öffnen", open_nav_on_click=True)
        self._add_tooltip(self.preview_btn, "Vorschau ein-/ausblenden (⌘⇧M)", open_nav_on_click=False)
        self._add_tooltip(self.tex_attach_btn, "Dateien für LaTeX auswählen,\nins Projekt kopieren und passenden Code einfügen", open_nav_on_click=False)
        self._add_tooltip(self.listbox, "Navigationsliste", open_nav_on_click=False)

        # --- Editor mit Zeilennummern + Scrollbar ---
        editor_wrap = tk.Frame(right, bg="#FFFFFF")
        editor_wrap.pack(fill="both", expand=True, padx=8, pady=8)
        editor_wrap.pack_propagate(False)
        self.editor_wrap = editor_wrap

        self.vscroll = ttk.Scrollbar(editor_wrap, orient="vertical")
        self.vscroll.pack(side="right", fill="y")
        self.hscroll = ttk.Scrollbar(editor_wrap, orient="horizontal")
        self.hscroll.pack(side="bottom", fill="x")

        self.linenos = tk.Text(
            editor_wrap, width=4, padx=8, pady=14, takefocus=0, border=0, highlightthickness=0,
            background="#F0F0F0", state="disabled",
            font=self._editor_font()
        )
        self.linenos.pack(side="left", fill="y")
        self.linenos.tag_configure("current_line_no")

        # Header-Buttons passend zum Zustand aktualisieren
        self._update_header_buttons()

        self.text = tk.Text(
            editor_wrap,
            wrap="word",
            yscrollcommand=self.vscroll.set,
            xscrollcommand=self.hscroll.set,
            undo=True, autoseparators=True, maxundo=1000,
            font=self._editor_font(),
            insertbackground="black",
            insertwidth=2,
            insertontime=600,
            insertofftime=300,
            bd=0,
            relief="flat",
            highlightthickness=0,
            padx=18,
            pady=14,
        )
        # Lint-Tag-Basiskonfiguration (Farben setzt _apply_theme)
        self.text.tag_configure("lint_error", underline=0)
        self.text.tag_configure("lint_warning", underline=0)
        self.text.tag_configure("lint_note", underline=0)
        self.text.tag_configure("current_line")

        # Editor packen
        self.text.pack(side="left", fill="both", expand=True)
        self.after_idle(self._sync_gutter_from_text)

        self.preview_wrap = tk.Frame(editor_wrap, bg="#FFFFFF", width=420)
        self.preview_wrap.pack_propagate(False)
        self.preview_header = tk.Label(
            self.preview_wrap,
            text="Vorschau",
            anchor="w",
            padx=12,
            pady=8,
            font=("Menlo", 11, "bold"),
        )
        self.preview_header.pack(fill="x")
        self.preview_text = tk.Text(
            self.preview_wrap,
            wrap="word",
            state="disabled",
            takefocus=0,
            bd=0,
            relief="flat",
            highlightthickness=0,
            padx=16,
            pady=12,
            font=("Georgia", 15),
            insertwidth=0,
            cursor="arrow",
        )
        self.preview_text.pack(fill="both", expand=True)
        self.preview_divider = tk.Frame(editor_wrap, width=1, bg="#D7DDE7")
        self.preview_wrap.bind("<Configure>", lambda _e: self._schedule_preview_update())

        # Destroy/Context/Modified
        self.text.bind("<Destroy>", self._on_text_destroy)
        self._build_text_context_menu()
        self.text.bind("<<Modified>>", self._on_text_modified)

        # Klammer-Tags
        self.text.tag_configure("brace_error", background="#FFCDD2")
        self.text.tag_configure("brace_match", background="#CFE8FF")

        # Sammel-Handler: Linenumbers / Syntax / Brace-Highlight / Statusbar
        def _on_text_activity(_=None):
            self._update_linenumbers()
            self._schedule_highlight()
            self._highlight_current_line()
            try:
                self._highlight_brace_at_cursor()
            except Exception:
                pass
            self._update_statusbar()
            try:
                self._sync_gutter_from_text()
            except Exception:
                pass
        self.text.bind("<KeyRelease>", _on_text_activity)
        self.text.bind("<Configure>",  _on_text_activity)
        self.text.bind("<ButtonRelease-1>", _on_text_activity)
        self.text.bind("<MouseWheel>", _on_text_activity)

        # Scrollbars → Text/Gutter
        self.vscroll.config(command=self._on_scrollbar)
        self.hscroll.config(command=self.text.xview)

        # ===== SCORE PANE =====
        score_pane = tk.Frame(self._right_split, bg="#F7F7FF")
        self._right_split.add(score_pane, weight=2)
        self.score_pane = score_pane  # für Theme

        # Controls-Leiste
        ctrl = tk.Frame(score_pane, bg="#F7F7FF")
        ctrl.pack(fill="x", padx=8, pady=(8, 0))
        self._score_ctrl = ctrl  # <<< wichtig: merken

        ttk.Button(ctrl, text="MAAT analysieren", command=self._analyze).pack(side="left")
        ttk.Button(ctrl, text="Notiz löschen", command=self._delete_note).pack(side="right", padx=6)
        self.code_toggle_btn = tk.Checkbutton(ctrl, text="Code", variable=self.code_mode, command=self._toggle_code_mode, bd=0, relief="flat", padx=6, pady=4)
        self.code_toggle_btn.pack(side="left", padx=6)

        # Run/Linter-Buttons: erstellen, aber NICHT packen
        self.run_btn = ttk.Button(ctrl, text="PY testen ▶", command=self._run_python)
        self.linter_btn = ttk.Button(ctrl, text="Linter", command=self._run_linter)

        # Falls beim Start bereits Code‑Modus aktiv ist → packen
        if self.code_mode.get():
            self.run_btn.pack(side="left", padx=6)
            self.linter_btn.pack(side="left", padx=6)

        # Interpreter-Zustand initial prüfen
        try:
            self._sync_editor_mode_state()
        except Exception:
            pass

        # Shortcuts fürs Ausführen
        self.bind_all("<Command-Return>", lambda e: self._run_python())
        self.bind_all("<Command-KP_Enter>", lambda e: self._run_python())

        # Scores
        scores_row = tk.Frame(score_pane, bg="#F7F7FF")
        scores_row.pack(fill="x", padx=8, pady=8)
        self.scores_row = scores_row  # für Theme

        self.score_labels = {}
        self._score_boxes = []

        for column, p in enumerate(PRINCIPLES):
            f = tk.Frame(scores_row, bg="#F7F7FF")
            f.grid(row=0, column=column, sticky="nsew", padx=(0, 6), pady=4)
            scores_row.columnconfigure(column, weight=1, uniform="scores")

            name_lbl = tk.Label(f, text=p, fg=COLORS[p], bg="#F7F7FF")
            name_lbl.principle = p
            name_lbl.pack()

            var = tk.StringVar(value="–")
            val_lbl = tk.Label(f, textvariable=var, bg="#F7F7FF")
            val_lbl.pack()

            self.score_labels[p] = var
            self._score_boxes.append({"frame": f, "name": name_lbl, "value": val_lbl, "principle": p})

        # Schnellsuche unter den Prinzipien
        quick_row = tk.Frame(score_pane, bg="#F7F7FF")
        quick_row.pack(fill="x", padx=8, pady=(0, 8))
        self.quickfind_row = quick_row

        self.quickfind_label = tk.Label(quick_row, text="IM DOKUMENT", font=self._ui_font(9, "bold"), bg="#F7F7FF")
        self.quickfind_label.pack(side="left")

        self.quickfind_var = tk.StringVar(value="")
        self.quickfind_entry = tk.Entry(quick_row, textvariable=self.quickfind_var, width=24)
        self.quickfind_entry.pack(side="left", padx=6)

        ttk.Button(quick_row, text="◀︎", width=3, command=self._quickfind_prev).pack(side="left", padx=(4, 0))
        ttk.Button(quick_row, text="▶︎", width=3, command=self._quickfind_next).pack(side="left", padx=(2, 0))
        ttk.Button(quick_row, text="✕", width=3, command=self._quickfind_clear).pack(side="left", padx=6)

        self.quickfind_entry.bind("<Return>",       lambda e: self._quickfind_next())
        self.quickfind_entry.bind("<Shift-Return>", lambda e: self._quickfind_prev())
        self.quickfind_var.trace_add("write", lambda *_: self._quickfind_update())
        self._build_input_context_menu()

        self.maat_var = tk.StringVar(value="MAAT: –")
        self.maat_summary = tk.Label(scores_row, textvariable=self.maat_var, fg="#111111", bg="#F7F7FF",
                                    font=self._ui_font(12, "bold"), padx=12)
        self.maat_summary.grid(row=0, column=len(PRINCIPLES), sticky="ns")

        # Linter‑Leiste gemäß Modus zeigen/verstecken
        try:
            self._ensure_linter_ui(show=self.code_mode.get())
        except Exception:
            pass

        # Sash-Positionen herstellen
        self.after(50, self._restore_sashes)
#BUILD LAYOUT DESIGN ERSTELLT

    def _ensure_linter_ui(self, show: bool):
        """Erstellt die Linter-Liste bei Bedarf und blendet sie passend ein/aus."""
        if not getattr(self, "score_pane", None):
            return

        if not getattr(self, "linter_frame", None) or not self.linter_frame.winfo_exists():
            frame = tk.Frame(self.score_pane, bg="#F7F7FF")
            label = tk.Label(frame, text="Linter", anchor="w", bg="#F7F7FF")
            label.pack(fill="x", padx=8, pady=(0, 4))

            list_wrap = tk.Frame(frame, bg="#F7F7FF")
            list_wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))

            scroll = tk.Scrollbar(list_wrap, orient="vertical")
            listbox = tk.Listbox(list_wrap, height=6, activestyle="none", yscrollcommand=scroll.set)
            scroll.config(command=listbox.yview)
            listbox.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")

            self.linter_frame = frame
            self.linter_label = label
            self.linter_list = listbox

        if show:
            if not self.linter_frame.winfo_manager():
                self.linter_frame.pack(fill="both", expand=False)
        else:
            self.linter_frame.pack_forget()

        try:
            self._apply_theme()
        except Exception:
            pass
      
    def _quickfind_update(self):
        """Live‑Treffer hervorheben, ohne den Cursor zu bewegen."""
        q = (self.quickfind_var.get() or "").strip()
        # leere Suche: Tags löschen & Status zurücksetzen
        if not q:
            try:
                self.text.tag_remove("find_all", "1.0", "end")
                self.text.tag_remove("find_current", "1.0", "end")
            except Exception:
                pass
            self._update_statusbar()
            return
        # gleiche Optionen wie im Find‑Dialog weiterverwenden
        case  = bool(self._last_find.get("case", False))
        regex = bool(self._last_find.get("regex", False))
        self._apply_find_all(q, case, regex)
        self._update_statusbar()

    def _quickfind_next(self):
        q = (self.quickfind_var.get() or "").strip()
        if not q:
            return
        case  = bool(self._last_find.get("case", False))
        regex = bool(self._last_find.get("regex", False))
        self._apply_find_all(q, case, regex)
        self._apply_find_move(q, case, regex, forward=True)
        self._update_statusbar()

    def _quickfind_prev(self):
        q = (self.quickfind_var.get() or "").strip()
        if not q:
            return
        case  = bool(self._last_find.get("case", False))
        regex = bool(self._last_find.get("regex", False))
        self._apply_find_all(q, case, regex)
        self._apply_find_move(q, case, regex, forward=False)
        self._update_statusbar()

    def _quickfind_clear(self):
        """Schnellsuche leeren & Markierungen entfernen."""
        try:
            self.quickfind_var.set("")
        except Exception:
            pass
        try:
            self.text.tag_remove("find_all", "1.0", "end")
            self.text.tag_remove("find_current", "1.0", "end")
        except Exception:
            pass
        self._update_statusbar()

    def _text_alive(self) -> bool:
        """True, wenn self.text existiert und das Tk-Widget noch lebt."""
        try:
            return hasattr(self, "text") and self.text.winfo_exists()
        except Exception:
            return False
#Mausklick Helper



#Rechtklick Tasten
    def _build_text_context_menu(self):
        """Rechtsklick-Menü des Editors (ein Menü, alles drin)."""
        self.text_ctx = tk.Menu(self, tearoff=0)

        # Undo / Redo (Index 0/1 – wichtig für dynamisches En/Disablen)
        self.text_ctx.add_command(
            label="Rückgängig", accelerator="⌘Z",
            command=lambda: self._editor_event("undo")
        )
        self.text_ctx.add_command(
            label="Wiederholen", accelerator="⇧⌘Z",
            command=lambda: self._editor_event("redo")
        )
        self.text_ctx.add_separator()

        # Standard
        self.text_ctx.add_command(
            label="Ausschneiden", accelerator="⌘X",
            command=lambda: self._ctx_event("<<Cut>>")
        )
        self.text_ctx.add_command(
            label="Kopieren", accelerator="⌘C",
            command=lambda: self._ctx_event("<<Copy>>")
        )
        self.text_ctx.add_command(
            label="Einfügen", accelerator="⌘V",
            command=lambda: self._ctx_event("<<Paste>>")
        )
        self.text_ctx.add_separator()
        self.text_ctx.add_command(
            label="Suchen…", accelerator="⌘F",
            command=self._open_find
        )
        self.text_ctx.add_command(
            label="Ersetzen…", accelerator="⌘H",
            command=self._open_replace
        )
        self.text_ctx.add_separator()
        self.text_ctx.add_command(
            label="Alle markieren", accelerator="⌘A",
            command=self._ctx_select_all
        )


        # Plattformfreundliche Trigger – Handler liefert 'break', damit Selektion nicht verschwindet
        self._bind_context_menu(self.text, self._on_text_context)
        self.text.bind("<ButtonPress>", self._on_text_context_press, add="+")
        self.text.bind("<ButtonRelease>", self._on_text_context_release, add="+")

        # Tastenkürzel (Undo/Redo plattformweit)
        self.text.bind("<Command-z>",       lambda e: self._editor_event("undo"))
        self.text.bind("<Shift-Command-Z>", lambda e: self._editor_event("redo"))
        self.text.bind("<Control-z>",       lambda e: self._editor_event("undo"))
        self.text.bind("<Control-y>",       lambda e: self._editor_event("redo"))
        self.text.bind("<Control-Shift-Z>", lambda e: self._editor_event("redo"))

    def _build_input_context_menu(self):
        """Kontextmenü für Eingabefelder wie Titel, Suche und Schnellsuche."""
        self.input_ctx = tk.Menu(self, tearoff=0)
        self.input_ctx.add_command(
            label="Ausschneiden", accelerator="⌘X",
            command=lambda: self._input_ctx_event("<<Cut>>")
        )
        self.input_ctx.add_command(
            label="Kopieren", accelerator="⌘C",
            command=lambda: self._input_ctx_event("<<Copy>>")
        )
        self.input_ctx.add_command(
            label="Einfügen", accelerator="⌘V",
            command=lambda: self._input_ctx_event("<<Paste>>")
        )
        self.input_ctx.add_separator()
        self.input_ctx.add_command(
            label="Alles markieren", accelerator="⌘A",
            command=self._input_ctx_select_all
        )

        for widget in (getattr(self, "title_entry", None), getattr(self, "search_entry", None), getattr(self, "quickfind_entry", None)):
            if widget is not None:
                self._bind_context_menu(widget, self._on_input_context)
                widget.bind("<ButtonPress>", self._on_input_context_press, add="+")
                widget.bind("<ButtonRelease>", self._on_input_context_release, add="+")

    def _bind_context_menu(self, widget, handler):
        try:
            for sequence in (
                "<Button-3>",
                "<ButtonRelease-3>",
                "<Button-2>",
                "<ButtonRelease-2>",
                "<Control-Button-1>",
                "<Control-ButtonRelease-1>",
            ):
                widget.bind(sequence, handler, add="+")
        except Exception:
            pass

    def _context_popup_allowed(self, event, *, window_s=0.35):
        try:
            widget_name = str(getattr(event, "widget", ""))
            x_root = int(getattr(event, "x_root", -1))
            y_root = int(getattr(event, "y_root", -1))
        except Exception:
            widget_name, x_root, y_root = "", -1, -1

        signature = (widget_name, x_root, y_root)
        now = time.monotonic()
        last = getattr(self, "_last_context_popup", None)
        if last and last[0] == signature and (now - last[1]) < window_s:
            return False
        self._last_context_popup = (signature, now)
        return True

    def _is_context_mouse_event(self, event):
        try:
            num = int(getattr(event, "num", 0) or 0)
        except Exception:
            num = 0
        try:
            state = int(getattr(event, "state", 0) or 0)
        except Exception:
            state = 0
        control_down = bool(state & 0x0004)
        return num in (2, 3) or (num == 1 and control_down)

    def _snapshot_event(self, event):
        return SimpleNamespace(
            x=getattr(event, "x", 0),
            y=getattr(event, "y", 0),
            x_root=getattr(event, "x_root", 0),
            y_root=getattr(event, "y_root", 0),
            widget=getattr(event, "widget", None),
            num=getattr(event, "num", None),
            state=getattr(event, "state", 0),
        )

    def _on_text_context_press(self, event):
        if not self._is_context_mouse_event(event):
            return
        self._pending_text_context = self._snapshot_event(event)
        return "break"

    def _on_text_context_release(self, event):
        if not self._is_context_mouse_event(event):
            return
        evt = self._snapshot_event(getattr(self, "_pending_text_context", None) or event)
        self._pending_text_context = None
        if self._context_popup_allowed(evt):
            self.after_idle(lambda ev=evt: self._show_text_context_menu(ev))
        return "break"

    def _on_input_context_press(self, event):
        if not self._is_context_mouse_event(event):
            return
        self._pending_input_context = self._snapshot_event(event)
        return "break"

    def _on_input_context_release(self, event):
        if not self._is_context_mouse_event(event):
            return
        evt = self._snapshot_event(getattr(self, "_pending_input_context", None) or event)
        self._pending_input_context = None
        if self._context_popup_allowed(evt):
            self.after_idle(lambda ev=evt: self._show_input_context_menu(ev))
        return "break"
    
    def _on_text_context(self, event):
        """Wrapper, der das Kontextmenü zeigt und immer 'break' zurückgibt."""
        try:
            if self._context_popup_allowed(event):
                evt = self._snapshot_event(event)
                self.after_idle(lambda ev=evt: self._show_text_context_menu(ev))
        finally:
            return "break"

    def _on_input_context(self, event):
        """Wrapper für Kontextmenüs in Entry-Feldern."""
        try:
            if self._context_popup_allowed(event):
                evt = self._snapshot_event(event)
                self.after_idle(lambda ev=evt: self._show_input_context_menu(ev))
        finally:
            return "break"
    
    def _block_span(self):
        """Gibt (start_index, end_index, original_text) über volle Zeilen zurück.
        Nutzt 'sel' wenn vorhanden, sonst die Cursor-Zeile."""
        if self.text.tag_ranges("sel"):
            start = self.text.index("sel.first linestart")
            end   = self.text.index("sel.last lineend")
        else:
            start = self.text.index("insert linestart")
            end   = self.text.index("insert lineend")
        return start, end, self.text.get(start, end)

    def _editor_event(self, action):
        try:
            if action == "undo":
                self.text.edit_undo()
            elif action == "redo":
                self.text.edit_redo()
            elif action == "cut":
                self.text.event_generate("<<Cut>>")
            elif action == "copy":
                self.text.event_generate("<<Copy>>")
            elif action == "paste":
                self.text.event_generate("<<Paste>>")
            elif action == "select_all":
                self._ctx_select_all()
        except tk.TclError:
            pass

    def _text_context_selection_range(self):
        try:
            ranges = self.text.tag_ranges("sel")
            if len(ranges) >= 2:
                return str(ranges[0]), str(ranges[1])
        except Exception:
            pass
        saved = getattr(self, "_text_context_selection", None)
        if isinstance(saved, tuple) and len(saved) == 2:
            return saved
        return None

    def _ctx_copy(self):
        rng = self._text_context_selection_range()
        if not rng:
            return
        try:
            data = self.text.get(rng[0], rng[1])
            self.clipboard_clear()
            self.clipboard_append(data)
        except Exception:
            pass

    def _ctx_cut(self):
        rng = self._text_context_selection_range()
        if not rng:
            return
        try:
            data = self.text.get(rng[0], rng[1])
            self.clipboard_clear()
            self.clipboard_append(data)
            self.text.focus_set()
            self.text.edit_separator()
            self.text.delete(rng[0], rng[1])
            self.text.edit_separator()
            self.text.edit_modified(True)
            self._on_text_modified()
        except Exception:
            pass

    def _ctx_paste(self):
        try:
            data = self.clipboard_get()
        except Exception:
            return

        rng = self._text_context_selection_range()
        insert_at = getattr(self, "_text_context_insert", None)
        try:
            self.text.focus_set()
            self.text.edit_separator()
            if rng:
                self.text.delete(rng[0], rng[1])
                insert_at = rng[0]
            if not insert_at:
                insert_at = self.text.index("insert")
            self.text.insert(insert_at, data)
            self.text.mark_set("insert", f"{insert_at}+{len(data)}c")
            self.text.edit_separator()
            self.text.edit_modified(True)
            self._on_text_modified()
        except Exception:
            pass

    def _ctx_event(self, virtual_event):
        try:
            if virtual_event == "<<Copy>>":
                self._ctx_copy()
            elif virtual_event == "<<Cut>>":
                self._ctx_cut()
            elif virtual_event == "<<Paste>>":
                self._ctx_paste()
            else:
                self.text.focus_set()
                self.update_idletasks()
                self.text.event_generate(virtual_event)
        except Exception:
            pass

    def _input_context_selection_range(self, widget):
        try:
            if isinstance(widget, tk.Entry) and widget.selection_present():
                return int(widget.index("sel.first")), int(widget.index("sel.last"))
        except Exception:
            pass
        saved = getattr(self, "_input_context_selection", None)
        if isinstance(saved, tuple) and len(saved) == 2:
            return int(saved[0]), int(saved[1])
        return None

    def _input_ctx_copy(self, widget):
        rng = self._input_context_selection_range(widget)
        if not rng:
            return
        try:
            data = widget.get()[rng[0]:rng[1]]
            self.clipboard_clear()
            self.clipboard_append(data)
        except Exception:
            pass

    def _input_ctx_cut(self, widget):
        rng = self._input_context_selection_range(widget)
        if not rng:
            return
        try:
            value = widget.get()
            data = value[rng[0]:rng[1]]
            self.clipboard_clear()
            self.clipboard_append(data)
            widget.focus_set()
            widget.delete(rng[0], rng[1])
            widget.icursor(rng[0])
        except Exception:
            pass

    def _input_ctx_paste(self, widget):
        try:
            data = self.clipboard_get()
        except Exception:
            return
        rng = self._input_context_selection_range(widget)
        try:
            widget.focus_set()
            if rng:
                widget.delete(rng[0], rng[1])
                insert_at = rng[0]
            else:
                insert_at = int(getattr(self, "_input_context_insert", widget.index("insert")))
            widget.insert(insert_at, data)
            widget.icursor(insert_at + len(data))
        except Exception:
            pass

    def _input_ctx_event(self, virtual_event):
        widget = getattr(self, "_context_widget", None)
        if widget is None:
            return
        try:
            if virtual_event == "<<Copy>>":
                self._input_ctx_copy(widget)
            elif virtual_event == "<<Cut>>":
                self._input_ctx_cut(widget)
            elif virtual_event == "<<Paste>>":
                self._input_ctx_paste(widget)
            else:
                widget.focus_set()
                self.update_idletasks()
                widget.event_generate(virtual_event)
        except Exception:
            pass

    def _input_ctx_select_all(self):
        widget = getattr(self, "_context_widget", None)
        if widget is None:
            return
        try:
            if isinstance(widget, tk.Entry):
                widget.selection_range(0, "end")
                widget.icursor("end")
            else:
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "1.0")
        except Exception:
            pass

    def _get_selection_or_all_lines(self):
        """Gibt (start, end) so zurück, dass immer ganze Zeilen erwischt werden.
        Falls keine Auswahl → gesamter Text."""
        try:
            start = self.text.index("sel.first linestart")
            end   = self.text.index("sel.last lineend")
        except Exception:
            start = "1.0"
            end   = "end-1c"
        return start, end

    def _indent_block(self, steps: int = 1, width: int = 4, include_blank: bool = False):
        """Rückt Auswahl/aktuellen Zeilenblock relativ um steps × width Spaces nach rechts ein.
        - include_blank=False: leere Zeilen bleiben unverändert
        """
        try:
            # Arbeitsbereich: Auswahl → ganze Zeilen, sonst Cursorzeile
            if self.text.tag_ranges("sel"):
                start = self.text.index("sel.first linestart")
                end   = self.text.index("sel.last lineend")
            else:
                start = self.text.index("insert linestart")
                end   = self.text.index("insert lineend")

            block = self.text.get(start, end)
        except Exception:
            return

        steps = max(1, int(steps))
        width = max(1, int(width))
        pad   = " " * (steps * width)

        # Zeilen inklusive Zeilenende trennen → EOLs erhalten
        lines = block.splitlines(keepends=True)

        # Nicht-leere Zeilen einrücken; leere nur wenn include_blank=True
        new_lines = []
        for ln in lines:
            if ln.strip() == "":
                new_lines.append((pad + ln) if include_blank else ln)
            else:
                new_lines.append(pad + ln)

        new_text = "".join(new_lines)

        # Undo-freundlich ersetzen
        try:
            self.text.edit_separator()
            self.text.delete(start, end)
            self.text.insert(start, new_text)
            self.text.edit_separator()
        except Exception:
            return

        # Auswahl & Cursor sauber setzen
        try:
            self.text.tag_remove("sel", "1.0", "end")
            self.text.tag_add("sel", start, f"{start}+{len(new_text)}c")
            self.text.mark_set("insert", start)
            self.text.see(start)
        except Exception:
            pass

        # UI aktualisieren
        try: self._update_linenumbers()
        except Exception: pass
        try: self._schedule_highlight()
        except Exception: pass
        try: self._update_statusbar()
        except Exception: pass

    def _dedent_block(self, levels: int = 1):
        """Verschiebt Auswahl/alle Zeilen um levels × 4 Spaces nach links (so weit möglich)."""
        levels = max(1, int(levels))
        remove = 4 * levels
        start, end = self._get_selection_or_all_lines()
        try:
            block = self.text.get(start, end)
        except Exception:
            return

        new_lines = []
        for ln in block.split("\n"):
            if ln.strip() == "":
                new_lines.append(ln)
                continue
            # führende Whitespaces zählen (Tabs ≈ 4 Spaces behandeln)
            lead = 0
            for ch in ln:
                if ch == " ":
                    lead += 1
                elif ch == "\t":
                    lead += 4
                else:
                    break
            # so viel wie möglich entfernen (aber nicht ins Negative)
            take = min(remove, lead)
            # baue neue führende Whitespaces (Spaces)
            new_prefix = " " * (lead - take)
            # Rest der Zeile ohne ursprüngliche führende Whitespace
            stripped = ln.lstrip(" \t")
            new_lines.append(new_prefix + stripped)

        new_text = "\n".join(new_lines)

        try:
            self.text.edit_separator()
            self.text.delete(start, end)
            self.text.insert(start, new_text)
            self.text.edit_separator()
        except Exception:
            return

        try:
            self.text.tag_remove("sel", "1.0", "end")
            new_end = self.text.index(f"{start}+{len(new_text)}c")
            self.text.tag_add("sel", start, new_end)
        except Exception:
            pass

        try: self._update_linenumbers()
        except Exception: pass
        try: self._schedule_highlight()
        except Exception: pass
        try: self._update_statusbar()
        except Exception: pass
#Stabilität
    def _schedule_highlight(self, delay_ms: int = 120):
        """Debounce: starte Syntax‑Highlight nach kurzer Pause."""
        try:
            if getattr(self, "_hl_after", None):
                self.after_cancel(self._hl_after)
        except Exception:
            pass
        try:
            self._hl_after = self.after(delay_ms, self._highlight_now)
        except Exception:
            self._highlight_now()

    def _highlight_now(self):
        """Jetzt wirklich highlighten (oder no-op, wenn keine Routine existiert)."""
        self._hl_after = None
        try:
            if hasattr(self, "_highlight_syntax"):
                self._highlight_syntax()
                return
        except Exception:
            pass
        return

    def _on_text_destroy(self, _=None):
        """Aufräumen: pending Jobs abbrechen, wenn das Text-Widget zerstört wird."""
        try:
            if getattr(self, "_hl_after", None):
                self.after_cancel(self._hl_after)
                self._hl_after = None
            self._pending_external_paths = []
        except Exception:
            pass

#Ende 


    def _ctx_select_all(self):
        try:
            self.text.tag_add("sel", "1.0", "end-1c")
            self.text.mark_set("insert", "1.0")
            self.text.see("insert")
        except Exception:
            pass

    def _widget_has_selection(self, widget) -> bool:
        try:
            if isinstance(widget, tk.Entry):
                return bool(widget.selection_present())
            return bool(widget.tag_ranges("sel"))
        except Exception:
            return False

    def _entry_index_in_selection(self, widget, idx) -> bool:
        try:
            start = int(widget.index("sel.first"))
            end = int(widget.index("sel.last"))
            pos = int(widget.index(idx))
            return start <= pos < end
        except Exception:
            return False

    def _index_in_selection(self, idx) -> bool:
        try:
            start = self.text.index("sel.first")
            end = self.text.index("sel.last")
            return self.text.compare(idx, ">=", start) and self.text.compare(idx, "<", end)
        except Exception:
            return False

    def _show_text_context_menu(self, event):
        """Kontextmenü dynamisch aktualisieren und anzeigen."""
        try:
            ranges = self.text.tag_ranges("sel")
            self._text_context_selection = (str(ranges[0]), str(ranges[1])) if len(ranges) >= 2 else None
        except Exception:
            self._text_context_selection = None

        # --- Auswahlstatus für Cut/Copy ---
        try:
            has_sel = bool(self._text_context_selection)
        except Exception:
            has_sel = False
        self.text_ctx.entryconfig("Ausschneiden", state=("normal" if has_sel else "disabled"))
        self.text_ctx.entryconfig("Kopieren",     state=("normal" if has_sel else "disabled"))

        # --- Einfügen: nur wenn Clipboard-Inhalt vorhanden ---
        try:
            _ = self.clipboard_get()
            can_paste = True
        except Exception:
            can_paste = False
        self.text_ctx.entryconfig("Einfügen", state=("normal" if can_paste else "disabled"))

        try:
            can_undo = bool(int(self.text.edit_modified()))
        except Exception:
            can_undo = True
        can_redo = True

        # Menüeinträge per Index setzen:
        # 0 = Rückgängig, 1 = Wiederholen (so wie beim Aufbau in _build_text_context_menu)
        try:
            self.text_ctx.entryconfig(0, state=("normal" if can_undo else "disabled"))
            self.text_ctx.entryconfig(1, state=("normal" if can_redo else "disabled"))
        except Exception:
            pass

        try:
            idx = self.text.index(f"@{event.x},{event.y}")
        except Exception:
            idx = self.text.index("insert")
        self._text_context_insert = idx

        if not self._index_in_selection(idx):
            try:
                self.text.mark_set("insert", idx)
                self.text.see(idx)
            except Exception:
                pass

        try:
            self.text.focus_set()
        except Exception:
            pass

        try:
            self.text_ctx.tk_popup(event.x_root, event.y_root)
        except Exception:
            try:
                self.text_ctx.post(event.x_root, event.y_root)
            except Exception:
                pass
        finally:
            try:
                self.text_ctx.grab_release()
            except Exception:
                pass

    def _show_input_context_menu(self, event):
        widget = getattr(event, "widget", None)
        if widget is None or not getattr(self, "input_ctx", None):
            return

        self._context_widget = widget
        try:
            if isinstance(widget, tk.Entry) and widget.selection_present():
                self._input_context_selection = (int(widget.index("sel.first")), int(widget.index("sel.last")))
            else:
                self._input_context_selection = None
        except Exception:
            self._input_context_selection = None

        state = "normal"
        try:
            state = str(widget.cget("state"))
        except Exception:
            pass
        editable = state not in {"disabled", "readonly"}
        has_sel = self._widget_has_selection(widget)

        self.input_ctx.entryconfig("Ausschneiden", state=("normal" if editable and has_sel else "disabled"))
        self.input_ctx.entryconfig("Kopieren", state=("normal" if has_sel else "disabled"))

        try:
            _ = self.clipboard_get()
            can_paste = True
        except Exception:
            can_paste = False
        self.input_ctx.entryconfig("Einfügen", state=("normal" if editable and can_paste else "disabled"))
        self.input_ctx.entryconfig("Alles markieren", state="normal")

        try:
            idx = widget.index(f"@{event.x}")
        except Exception:
            idx = None
        self._input_context_insert = idx

        if idx is not None and isinstance(widget, tk.Entry) and not self._entry_index_in_selection(widget, idx):
            try:
                widget.icursor(idx)
                widget.select_clear()
            except Exception:
                pass

        try:
            widget.focus_set()
        except Exception:
            pass

        try:
            self.input_ctx.tk_popup(event.x_root, event.y_root)
        except Exception:
            try:
                self.input_ctx.post(event.x_root, event.y_root)
            except Exception:
                pass
        finally:
            try:
                self.input_ctx.grab_release()
            except Exception:
                pass

#Automatische Einrückung 
    def _reindent(self, levels: int, scope: str = "auto"):
        """
        Setzt die Einrückung aller NICHT-leeren Zeilen auf levels × 4 Spaces.
        - scope="auto": wenn Auswahl existiert → nur Auswahl (volle Zeilen),
                        sonst das ganze Dokument.
        - scope="selection": immer nur Auswahl.
        - scope="all": immer gesamtes Dokument.
        - Tabs werden normalisiert zu Spaces, leere Zeilen bleiben unverändert.
        """
        try:
            # Bereich bestimmen
            has_sel = bool(self.text.tag_ranges("sel"))
            if scope == "selection" or (scope == "auto" and has_sel):
                start_idx = self.text.index("sel.first linestart")
                end_idx   = self.text.index("sel.last lineend")
                restore_selection = True
            else:
                start_idx = "1.0"
                end_idx   = "end-1c"
                restore_selection = False

            block = self.text.get(start_idx, end_idx)
        except Exception:
            return

        # clamp & vorbereiten
        try:
            levels = max(0, min(int(levels), 8))
        except Exception:
            levels = 0
        indent = " " * (4 * levels)

        # bearbeiten (Zeilenenden beibehalten!)
        lines = block.splitlines(keepends=True)
        new_lines = []
        for line in lines:
            if line.strip() == "":
                new_lines.append(line)  # leere Zeile unberührt
            else:
                stripped = line.lstrip(" \t")
                new_lines.append(indent + stripped)

        new_block = "".join(new_lines)

        # Undo-freundlich austauschen
        try:
            self.text.edit_separator()
            self.text.delete(start_idx, end_idx)
            self.text.insert(start_idx, new_block)
            self.text.edit_separator()
        except Exception:
            return

        # Auswahl wiederherstellen
        if restore_selection:
            try:
                new_end = self.text.index(f"{start_idx}+{len(new_block)}c")
                self.text.tag_remove("sel", "1.0", "end")
                self.text.tag_add("sel", start_idx, new_end)
            except Exception:
                pass

        # UI aktualisieren
        self._dirty = True
        for fn in (self._update_linenumbers,
                   self._schedule_highlight,
                   self._update_statusbar):
            try:
                fn()
            except Exception:
                pass

#Stabilität Schnellsuche

    def _quick_search_click(self, forward: bool = True):
        """
        'Schnellsuche': Nimmt (1) Selektion, (2) Wort unter Cursor, (3) letzten Begriff
        und springt zum nächsten/vorherigen Treffer. Markiert alle Treffer.
        """
        try:
            # 1) aktives Suchwort bestimmen
            q = ""
            try:
                q = self.text.get("sel.first", "sel.last")
            except Exception:
                pass

            if not q:
                # Wort unter dem Cursor nehmen
                i = self.text.index("insert")
                # Wortgrenzen: links/rechts zum whitespace
                start = self.text.search(r"\m", i, regexp=True, backwards=True)
                end   = self.text.search(r"\M", i, regexp=True)
                # Fallbacks (falls \m/\M nicht unterstützt): nimm wordstart/wordend
                if not start:
                    start = self.text.index("insert wordstart")
                if not end:
                    end = self.text.index("insert wordend")
                try:
                    q = self.text.get(start, end)
                except Exception:
                    q = ""

            if not q:
                # Letzten Begriff probieren
                q = (self._last_find.get("q") or "").strip()

            if not q:
                self.status_message("Schnellsuche: kein Begriff gefunden.")
                return

            # 2) Flags übernehmen (du kannst hier auch fest 'case=False' etc. setzen)
            case  = bool(self._last_find.get("case", False))
            regex = bool(self._last_find.get("regex", False))

            # 3) Status merken und alle Treffer markieren
            self._last_find.update({"q": q, "case": case, "regex": regex})
            if hasattr(self, "_apply_find_all"):
                self._apply_find_all(q, case, regex)

            # 4) zum nächsten/prev springen
            if hasattr(self, "_apply_find_move"):
                self._apply_find_move(q, case, regex, forward=bool(forward))
            else:
                # Minimal-Fallback: normale find_next / find_prev benutzen
                if forward and hasattr(self, "_find_next"):
                    self._find_next()
                elif not forward and hasattr(self, "_find_prev"):
                    self._find_prev()

            # Fokus in den Editor holen (wichtig für direktes Weiter-Suchen mit ⌘G)
            try:
                self.text.focus_set()
            except Exception:
                pass

            # kleine Rückmeldung
            self.status_message(f"Suchen: „{q}“")

        except Exception as e:
            try:
                self.status_message(f"Schnellsuche-Fehler: {e}")
            except Exception:
                pass


    # ---------- Code-Mode & Highlight ----------
    def _sync_editor_mode_state(self):
        on = bool(self.code_mode.get())
        language = self._current_editor_language()

        # 1) Schrift & Zeilenumbruch
        editor_font = self._editor_font()
        try:
            self.text.configure(
                font=editor_font,
                wrap=("word" if language == "markdown" else "none") if on else "word"
            )
            self.linenos.configure(font=editor_font)
        except Exception:
            pass

        # 2) Tab-/Shift-Tab-Verhalten (Block-Indent/Dedent im Code-Modus)
        try:
            # Erst sicher alle relevanten Bindings lösen
            for seq in ("<Tab>", "<ISO_Left_Tab>", "<Shift-Tab>"):
                try:
                    self.text.unbind(seq)
                except Exception:
                    pass
            if on:
                self.text.bind("<Tab>", self._insert_tab)
                # macOS sendet oft ISO_Left_Tab für Shift+Tab
                self.text.bind("<ISO_Left_Tab>", self._shift_tab)
                self.text.bind("<Shift-Tab>", self._shift_tab)
        except Exception:
            pass

        # 3) Buttons (Run/Linter) nur im Code-Modus sichtbar
        try:
            parent = getattr(self, "_score_ctrl", self)

            # Run-Button sicherstellen
            if not getattr(self, "run_btn", None) or not self.run_btn.winfo_exists():
                self.run_btn = ttk.Button(parent, text="PY testen ▶", command=self._run_python)

            # Linter-Button sicherstellen
            if not getattr(self, "linter_btn", None) or not self.linter_btn.winfo_exists():
                self.linter_btn = ttk.Button(parent, text="Linter", command=self._run_linter)

            # Vor dem (Neu-)Packen immer entfernen, damit es keine Doppel-Packs gibt
            for b in (self.run_btn, self.linter_btn):
                try:
                    b.pack_forget()
                except Exception:
                    pass

            if on:
                try:
                    self._refresh_run_interpreter()
                except Exception:
                    pass

                run_kind = getattr(self, "_run_kind", None)

                # Reihenfolge: erst Linter, dann Run
                if run_kind == "python":
                    try:
                        self.linter_btn.pack(side="left", padx=6)
                    except Exception:
                        pass
                try:
                    if run_kind in {"python", "shell", "tex"}:
                        self.run_btn.pack(side="left", padx=6)
                except Exception:
                    pass
        except Exception:
            pass

        # 4) Linter-Leiste unter den Scores passend ein-/ausblenden
        try:
            self._ensure_linter_ui(show=bool(on and getattr(self, "_run_kind", None) == "python"))
        except Exception:
            pass

        # 5) Header-Buttons (Speichern / Notiz speichern) abhängig vom externen Datei‑Modus
        try:
            self._update_header_buttons()
        except Exception:
            pass
        try:
            self._update_editor_chrome()
        except Exception:
            pass
        try:
            self._update_markdown_preview_visibility()
        except Exception:
            pass

        # 6) Syntax-Highlight & Linenumbers neu anstoßen
        try:
            self._schedule_highlight()
        except Exception:
            pass
        try:
            self._schedule_preview_update()
        except Exception:
            pass
        try:
            self._update_linenumbers()
        except Exception:
            pass
        try:
            self._highlight_current_line()
        except Exception:
            pass

    def _toggle_code_mode(self):
        self._sync_editor_mode_state()
        try:
            self._sync_active_tab_from_editor()
        except Exception:
            pass


    def _import_external_as_note(self):
        """
        Übernimmt den aktuellen Editor-Inhalt als Notiz.
        Danach ist die Datei nicht mehr ‚extern‘ verknüpft.
        """
        if not getattr(self, "external_file", None):
            # Nichts externes offen – normales Speichern erledigt es
            self._save_note()
            return

        # Keep the original binding until saving has succeeded.
        try:
            self._save_note()
        finally:
            # Buttons/Labels aktualisieren
            self._update_header_buttons()
            try:
                self._sync_editor_mode_state()
            except Exception:
                pass

    def _current_document_hint(self) -> str | None:
        if getattr(self, "external_file", None):
            return self.external_file
        try:
            title = (self.title_var.get() or "").strip()
        except Exception:
            title = ""
        return title or None

    def _current_document_suffix(self) -> str:
        hint = self._current_document_hint()
        return Path(hint).suffix.lower() if hint else ""

    def _is_python_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() == ".py"

    def _is_markdown_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() in {".md", ".markdown"}

    def _is_json_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() == ".json"

    def _is_yaml_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() in {".yaml", ".yml"}

    def _is_rust_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() == ".rs"

    def _is_javascript_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() in {".js", ".mjs", ".cjs"}

    def _is_java_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() == ".java"

    def _is_batch_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() in {".bat", ".cmd"}

    def _is_powershell_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() == ".ps1"

    def _is_html_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() in {".html", ".htm"}

    def _is_css_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() == ".css"

    def _is_php_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() == ".php"

    def _is_tex_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() == ".tex"

    def _is_shell_file_path(self, path: str | None) -> bool:
        return bool(path) and Path(path).suffix.lower() in {".sh", ".command"}

    def _is_code_file_path(self, path: str | None) -> bool:
        return (
            self._is_python_file_path(path)
            or self._is_shell_file_path(path)
            or self._is_markdown_file_path(path)
            or self._is_json_file_path(path)
            or self._is_yaml_file_path(path)
            or self._is_rust_file_path(path)
            or self._is_javascript_file_path(path)
            or self._is_java_file_path(path)
            or self._is_batch_file_path(path)
            or self._is_powershell_file_path(path)
            or self._is_html_file_path(path)
            or self._is_css_file_path(path)
            or self._is_php_file_path(path)
            or self._is_tex_file_path(path)
        )

    def _current_external_suffix(self) -> str:
        path = getattr(self, "external_file", None)
        return Path(path).suffix.lower() if path else ""

    def _current_editor_language(self) -> str:
        ext = self._current_document_suffix()
        if ext == ".py":
            return "python"
        if ext in {".md", ".markdown"}:
            return "markdown"
        if ext == ".json":
            return "json"
        if ext in {".yaml", ".yml"}:
            return "yaml"
        if ext == ".rs":
            return "rust"
        if ext in {".js", ".mjs", ".cjs"}:
            return "javascript"
        if ext == ".java":
            return "java"
        if ext in {".bat", ".cmd"}:
            return "batch"
        if ext == ".ps1":
            return "powershell"
        if ext in {".html", ".htm"}:
            return "html"
        if ext == ".css":
            return "css"
        if ext == ".php":
            return "php"
        if ext == ".tex":
            return "tex"
        if ext in {".sh", ".command"}:
            return "shell"
        if ext:
            return "text"
        if bool(self.code_mode.get()):
            return "python"
        return "text"

    def _language_badge(self) -> tuple[str, str]:
        language = self._current_editor_language()
        if language == "python":
            return "PY", "#3776AB"
        if language == "markdown":
            return "MD", "#0F8C79"
        if language == "json":
            return "JSON", "#C58B00"
        if language == "yaml":
            return "YAML", "#CB5A5E"
        if language == "rust":
            return "RS", "#CE422B"
        if language == "javascript":
            return "JS", "#D1B300"
        if language == "java":
            return "JAVA", "#E76F00"
        if language == "batch":
            return "BAT", "#8A5A20"
        if language == "powershell":
            return "PS", "#2C78C5"
        if language == "html":
            return "HTML", "#E34F26"
        if language == "css":
            return "CSS", "#1572B6"
        if language == "php":
            return "PHP", "#777BB4"
        if language == "tex":
            return "TEX", "#C26B24"
        if language == "shell":
            return "SH", "#3FB950"
        return "TXT", "#6B7280"

    def _update_editor_chrome(self):
        """Aktualisiert Badge und editorartige UI-Hinweise passend zum Dokumenttyp."""
        if not getattr(self, "doc_type_badge", None):
            return

        text, badge_bg = self._language_badge()
        palette = self._palette()
        accent = palette["border"]
        try:
            self.doc_type_badge.configure(
                text=text,
                bg=badge_bg,
                fg=palette["badge_fg"],
            )
        except Exception:
            pass
        try:
            if getattr(self, "editor_wrap", None) and self.editor_wrap.winfo_exists():
                self.editor_wrap.configure(
                    highlightbackground=accent,
                    highlightcolor=palette["accent"],
                )
        except Exception:
            pass
        try:
            if getattr(self, "title_entry", None) and self.title_entry.winfo_exists():
                self.title_entry.configure(
                    font=self._ui_font(12),
                    highlightbackground=accent,
                    highlightcolor=palette["accent"],
                )
        except Exception:
            pass

    def _preview_language(self) -> str | None:
        language = self._current_editor_language()
        return language if language in {"markdown", "html", "tex"} else None

    def _markdown_preview_available(self) -> bool:
        return self._preview_language() is not None

    def _html_preview_fallback_text(self, src: str) -> str:
        text = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", "", src)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html_lib.unescape(text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip() or "(Leeres HTML-Dokument)"

    def _native_html_webview_available(self) -> bool:
        return bool(sys.platform == "darwin" and AppKit and Foundation and WebKit)

    def _html_uses_native_webview(self) -> bool:
        return self._preview_language() == "html" and self._native_html_webview_available()

    def _ensure_native_html_webview(self):
        if getattr(self, "_native_html_webview", None):
            return self._native_html_webview
        if not self._native_html_webview_available():
            return None
        try:
            self._native_html_webview = _NativeHTMLWebViewPreview()
        except Exception:
            self._native_html_webview = None
        return self._native_html_webview

    def _hide_native_html_webview(self):
        try:
            if getattr(self, "_native_html_webview", None):
                self._native_html_webview.hide()
        except Exception:
            pass

    def _close_native_html_webview(self):
        try:
            if getattr(self, "_native_html_webview", None):
                self._native_html_webview.close()
        except Exception:
            pass
        self._native_html_webview = None

    def _html_preview_base_dir(self) -> str | None:
        path = getattr(self, "external_file", None)
        if path:
            try:
                return str(Path(path).resolve().parent)
            except Exception:
                return os.path.dirname(path)
        try:
            return os.getcwd()
        except Exception:
            return None

    def _preview_target_pdf(self) -> str | None:
        path = getattr(self, "external_file", None)
        if self._is_tex_file_path(path):
            candidate = str(Path(path).with_suffix(".pdf"))
            if os.path.exists(candidate):
                return candidate
            return None

        cached = getattr(self, "_last_tex_pdf_path", None)
        if cached and os.path.exists(cached):
            return cached
        return None

    def _show_preview_text(self, header: str, content: str):
        if getattr(self, "preview_header", None):
            try:
                self.preview_header.configure(text=header)
            except Exception:
                pass
        if not getattr(self, "preview_text", None):
            return
        try:
            self._preview_image_ref = None
            self._preview_image_refs = []
            self.preview_text.configure(state="normal")
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", content)
            self.preview_text.configure(state="disabled")
            self.preview_text.yview_moveto(0.0)
        except Exception:
            pass

    def _show_preview_image(self, header: str, photo, caption: str | None = None):
        if getattr(self, "preview_header", None):
            try:
                self.preview_header.configure(text=header)
            except Exception:
                pass
        if not getattr(self, "preview_text", None):
            return
        try:
            self._preview_image_ref = photo
            self._preview_image_refs = [photo] if photo else []
            self.preview_text.configure(state="normal")
            self.preview_text.delete("1.0", "end")
            self.preview_text.image_create("end", image=photo)
            if caption:
                self.preview_text.insert("end", f"\n\n{caption}", ("pv_caption",))
            self.preview_text.configure(state="disabled")
            self.preview_text.yview_moveto(0.0)
        except Exception:
            pass

    def _show_preview_images(self, header: str, photos, caption: str | None = None):
        if getattr(self, "preview_header", None):
            try:
                self.preview_header.configure(text=header)
            except Exception:
                pass
        if not getattr(self, "preview_text", None):
            return

        image_refs = [photo for photo in list(photos or []) if photo is not None]
        if not image_refs:
            self._show_preview_text(header, "Keine PDF-Seiten zum Anzeigen gefunden.")
            return

        try:
            self._preview_image_ref = image_refs[0]
            self._preview_image_refs = image_refs
            self.preview_text.configure(state="normal")
            self.preview_text.delete("1.0", "end")
            for page_no, photo in enumerate(image_refs, start=1):
                self.preview_text.insert("end", f"Seite {page_no}\n", ("pv_caption",))
                self.preview_text.image_create("end", image=photo)
                self.preview_text.insert("end", "\n\n")
            if caption:
                self.preview_text.insert("end", f"{caption}\n", ("pv_caption",))
            self.preview_text.configure(state="disabled")
            self.preview_text.yview_moveto(0.0)
        except Exception:
            pass

    def _render_pdf_preview_images(self, pdf_path: str):
        from PIL import Image, ImageTk

        cache_root = Path(tempfile.gettempdir()) / "maat_notepad_pdf_preview"
        cache_root.mkdir(parents=True, exist_ok=True)

        try:
            mtime = os.path.getmtime(pdf_path)
        except Exception:
            mtime = 0

        pane_w = max(420, int(getattr(self, "preview_wrap", self).winfo_width() or 420))
        max_page_w = max(220, pane_w - 28)
        render_key = hashlib.sha1(f"{pdf_path}|{mtime}|pdf-pages-v2".encode("utf-8")).hexdigest()
        page_dir = cache_root / render_key
        page_dir.mkdir(parents=True, exist_ok=True)

        def collect_rasters():
            patterns = ("page-*.png", "page-*.jpg", "page-*.jpeg")
            paths = []
            for pattern in patterns:
                paths.extend(page_dir.glob(pattern))
            return sorted(paths)

        def find_tool(name: str, extra_paths):
            tool_path = shutil.which(name)
            if tool_path:
                return tool_path
            for candidate in extra_paths:
                if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                    return candidate
            return None

        rasters = collect_rasters()
        if not rasters:
            errors = []

            gs_path = find_tool("gs", ("/opt/homebrew/bin/gs", "/usr/local/bin/gs", "/opt/local/bin/gs"))
            if gs_path:
                proc = subprocess.run(
                    [
                        gs_path,
                        "-dSAFER",
                        "-dBATCH",
                        "-dNOPAUSE",
                        "-sDEVICE=png16m",
                        "-dTextAlphaBits=4",
                        "-dGraphicsAlphaBits=4",
                        "-r144",
                        f"-sOutputFile={page_dir / 'page-%04d.png'}",
                        pdf_path,
                    ],
                    capture_output=True,
                    text=True,
                )
                rasters = collect_rasters()
                if proc.returncode != 0 or not rasters:
                    errors.append(f"gs: {(proc.stderr or proc.stdout or 'keine Vorschau erzeugt').strip()}")
                    rasters = []

            if not rasters:
                magick_path = find_tool(
                    "magick",
                    ("/opt/homebrew/bin/magick", "/usr/local/bin/magick", "/opt/local/bin/magick"),
                )
                if magick_path:
                    proc = subprocess.run(
                        [
                            magick_path,
                            "-density",
                            "144",
                            pdf_path,
                            "-background",
                            "white",
                            "-alpha",
                            "remove",
                            "-alpha",
                            "off",
                            str(page_dir / "page-%04d.png"),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    rasters = collect_rasters()
                    if proc.returncode != 0 or not rasters:
                        errors.append(f"magick: {(proc.stderr or proc.stdout or 'keine Vorschau erzeugt').strip()}")
                        rasters = []

            if not rasters:
                fallback_png = page_dir / "page-0001.png"
                try:
                    proc = subprocess.run(
                        ["/usr/bin/sips", "-s", "format", "png", pdf_path, "--out", str(fallback_png)],
                        capture_output=True,
                        text=True,
                    )
                    if proc.returncode != 0 or not fallback_png.exists():
                        raise RuntimeError((proc.stderr or proc.stdout or "sips konnte kein PNG erzeugen").strip())
                    rasters = [fallback_png]
                except Exception as sips_error:
                    thumb_dir = page_dir / "single"
                    thumb_dir.mkdir(parents=True, exist_ok=True)
                    proc = subprocess.run(
                        ["/usr/bin/qlmanage", "-t", "-s", "1600", "-o", str(thumb_dir), pdf_path],
                        capture_output=True,
                        text=True,
                    )
                    candidates = sorted(
                        list(thumb_dir.glob("*.png")) + list(thumb_dir.glob("*.jpg")) + list(thumb_dir.glob("*.jpeg"))
                    )
                    if candidates:
                        target = page_dir / "page-0001.png"
                        shutil.copyfile(candidates[0], target)
                        rasters = [target]
                    else:
                        errors.append(
                            f"sips: {sips_error}\nqlmanage: {(proc.stderr or proc.stdout or 'keine Vorschau erzeugt').strip()}"
                        )

            if not rasters:
                raise RuntimeError("\n".join(errors) if errors else "Keine PDF-Vorschau erzeugt.")

        photos = []
        for raster_path in rasters:
            with Image.open(raster_path) as img:
                # Transparente PDF-Renderings auf Weiß legen, damit Seiten nicht schwarz erscheinen.
                if img.mode in {"RGBA", "LA"} or "transparency" in img.info:
                    rgba = img.convert("RGBA")
                    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    background.alpha_composite(rgba)
                    img = background.convert("RGB")
                else:
                    img = img.convert("RGB")
                if img.width > max_page_w:
                    scale = max_page_w / float(img.width)
                    img = img.resize((max_page_w, max(1, int(img.height * scale))), Image.LANCZOS)
                photos.append(ImageTk.PhotoImage(img.copy()))
        return photos

    def _refresh_tex_pdf_preview(self):
        pdf_path = self._preview_target_pdf()
        if not pdf_path:
            self._show_preview_text(
                "PDF-Vorschau",
                "Noch keine PDF gefunden.\n\nBaue die Datei mit `TEX bauen ▶`, dann werden hier alle PDF-Seiten angezeigt.",
            )
            return

        try:
            photos = self._render_pdf_preview_images(pdf_path)
        except Exception as e:
            self._show_preview_text(
                "PDF-Vorschau",
                f"Die PDF-Vorschau konnte nicht gerendert werden.\n\nDatei:\n{pdf_path}\n\nFehler:\n{e}",
            )
            return

        self._show_preview_images(
            "PDF-Vorschau",
            photos,
            caption=f"{os.path.basename(pdf_path)} · {len(photos)} Seite(n)",
        )

    def _refresh_html_preview(self):
        if not getattr(self, "preview_text", None):
            if not self._html_uses_native_webview():
                return

        src = self.text.get("1.0", "end-1c")
        if self._html_uses_native_webview():
            controller = self._ensure_native_html_webview()
            if controller:
                try:
                    title = (self.title_var.get() or "").strip()
                except Exception:
                    title = ""
                if not title:
                    try:
                        title = Path(getattr(self, "external_file", "")).name
                    except Exception:
                        title = ""
                try:
                    controller.load_html(src, base_dir=self._html_preview_base_dir(), title=(title or None))
                    return
                except Exception:
                    pass

        widget = self.preview_text

        try:
            yfrac = float(widget.yview()[0])
        except Exception:
            yfrac = 0.0

        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")

            parser = _HTMLPreviewParser(widget)
            parser.feed(src)
            parser.close()

            if not widget.get("1.0", "end-1c").strip():
                widget.insert("1.0", "(Leeres HTML-Dokument)")

            header = "HTML-Vorschau"
            if parser.document_title:
                header = f"{header} - {parser.document_title}"
            if getattr(self, "preview_header", None) and self.preview_header.winfo_exists():
                self.preview_header.configure(text=header)
        except Exception:
            try:
                widget.delete("1.0", "end")
                widget.insert("1.0", self._html_preview_fallback_text(src))
                if getattr(self, "preview_header", None) and self.preview_header.winfo_exists():
                    self.preview_header.configure(text="HTML-Vorschau")
            except Exception:
                pass
        finally:
            try:
                widget.configure(state="disabled")
                widget.yview_moveto(yfrac)
            except Exception:
                pass

    def _flip_markdown_preview(self):
        if not self._markdown_preview_available():
            self.status_message("Vorschau ist nur für Markdown, HTML und TeX verfügbar.")
            return "break"
        try:
            self.preview_mode.set(not bool(self.preview_mode.get()))
        except Exception:
            return "break"
        self._toggle_markdown_preview()
        return "break"

    def _toggle_markdown_preview(self):
        if not self._markdown_preview_available():
            self._update_markdown_preview_visibility()
            self.status_message("Vorschau ist nur für Markdown, HTML und TeX verfügbar.")
            return
        self._update_markdown_preview_visibility()
        self._schedule_preview_update()
        state = "aktiv" if self.preview_mode.get() else "aus"
        self.status_message(f"Vorschau {state}.")

    def _update_markdown_preview_visibility(self):
        preview_language = self._preview_language()
        can_preview = preview_language is not None
        use_native_webview = preview_language == "html" and self._native_html_webview_available()
        preview_active = can_preview and bool(self.preview_mode.get())
        visible = preview_active and not use_native_webview

        try:
            if getattr(self, "preview_btn", None) and self.preview_btn.winfo_exists():
                btn_label = "PDF" if preview_language == "tex" else "WebView" if use_native_webview else "Vorschau"
                self.preview_btn.configure(text=(f"{btn_label} an" if preview_active else btn_label))
                self.preview_btn.state(["!disabled"] if can_preview else ["disabled"])
        except Exception:
            pass

        try:
            if getattr(self, "preview_header", None) and self.preview_header.winfo_exists():
                header = {
                    "tex": "PDF-Vorschau",
                    "html": "WebView-Vorschau" if use_native_webview else "HTML-Vorschau",
                }.get(preview_language, "Markdown-Vorschau")
                self.preview_header.configure(text=header)
        except Exception:
            pass

        if not (preview_language == "html" and bool(self.preview_mode.get()) and use_native_webview):
            self._hide_native_html_webview()

        if not getattr(self, "preview_wrap", None):
            return

        try:
            if visible:
                if not self.preview_wrap.winfo_manager():
                    self.preview_wrap.pack(side="right", fill="both", expand=True)
                if getattr(self, "preview_divider", None) and not self.preview_divider.winfo_manager():
                    self.preview_divider.pack(side="right", fill="y", padx=(8, 8))
            else:
                if getattr(self, "preview_divider", None):
                    self.preview_divider.pack_forget()
                self.preview_wrap.pack_forget()
        except Exception:
            pass

    def _schedule_preview_update(self):
        if not getattr(self, "preview_text", None):
            return
        try:
            if getattr(self, "_preview_after", None):
                self.after_cancel(self._preview_after)
        except Exception:
            pass
        try:
            self._preview_after = self.after(120, self._refresh_markdown_preview)
        except Exception:
            pass

    def _preview_insert_inline(self, widget, text: str, base_tags=()):
        if not text:
            return
        pattern = re.compile(
            r"`([^`\n]+)`"
            r"|\[([^\]]+)\]\(([^)]+)\)"
            r"|\*\*([^*\n]+)\*\*|__([^_\n]+)__"
            r"|(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)"
        )
        pos = 0
        base_tags = tuple(base_tags or ())

        for match in pattern.finditer(text):
            if match.start() > pos:
                widget.insert("end", text[pos:match.start()], base_tags)

            if match.group(1) is not None:
                widget.insert("end", match.group(1), base_tags + ("pv_inline_code",))
            elif match.group(2) is not None:
                widget.insert("end", match.group(2), base_tags + ("pv_link",))
                if match.group(3):
                    widget.insert("end", f" ({match.group(3)})", base_tags + ("pv_link_url",))
            elif match.group(4) is not None or match.group(5) is not None:
                widget.insert("end", match.group(4) or match.group(5), base_tags + ("pv_strong",))
            else:
                widget.insert("end", match.group(6) or match.group(7) or "", base_tags + ("pv_em",))
            pos = match.end()

        if pos < len(text):
            widget.insert("end", text[pos:], base_tags)

    def _refresh_markdown_preview(self):
        if not getattr(self, "preview_text", None):
            return
        preview_language = self._preview_language()
        if not preview_language or not bool(self.preview_mode.get()):
            return
        if preview_language == "tex":
            self._refresh_tex_pdf_preview()
            return
        if preview_language == "html":
            self._refresh_html_preview()
            return

        src = self.text.get("1.0", "end-1c")
        widget = self.preview_text

        try:
            yfrac = float(widget.yview()[0])
        except Exception:
            yfrac = 0.0

        def is_special_line(line: str) -> bool:
            stripped = line.strip()
            if not stripped:
                return True
            return bool(
                re.match(r"^(#{1,6})\s+", stripped)
                or re.match(r"^```", stripped)
                or re.match(r"^>\s?", stripped)
                or re.match(r"^\s*(?:[-*+]|\d+\.)\s+", line)
                or re.match(r"^\s*(?:---|\*\*\*|___)\s*$", stripped)
            )

        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            lines = src.splitlines()
            i = 0
            in_code = False

            while i < len(lines):
                line = lines[i]
                stripped = line.strip()

                if in_code:
                    if stripped.startswith("```"):
                        fence_info = stripped[3:].strip()
                        widget.insert("end", f"[/{fence_info or 'code'}]\n\n", ("pv_code_fence",))
                        in_code = False
                    else:
                        widget.insert("end", line + "\n", ("pv_codeblock",))
                    i += 1
                    continue

                if not stripped:
                    widget.insert("end", "\n")
                    i += 1
                    continue

                if stripped.startswith("```"):
                    fence_info = stripped[3:].strip()
                    widget.insert("end", f"[{fence_info or 'code'}]\n", ("pv_code_fence",))
                    in_code = True
                    i += 1
                    continue

                header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
                if header_match:
                    hashes, content = header_match.groups()
                    tag = "pv_h1" if len(hashes) == 1 else "pv_h2" if len(hashes) == 2 else "pv_h3"
                    widget.insert("end", content.strip() + "\n\n", (tag,))
                    i += 1
                    continue

                if re.match(r"^\s*(?:---|\*\*\*|___)\s*$", stripped):
                    widget.insert("end", "-" * 28 + "\n\n", ("pv_rule",))
                    i += 1
                    continue

                quote_match = re.match(r"^>\s?(.*)$", stripped)
                if quote_match:
                    self._preview_insert_inline(widget, f"| {quote_match.group(1).strip()}", ("pv_quote",))
                    widget.insert("end", "\n")
                    i += 1
                    continue

                list_match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
                if list_match:
                    indent, marker, content = list_match.groups()
                    level = max(0, len(indent.expandtabs(2)) // 2)
                    prefix = ("  " * level) + (f"{marker} " if marker.endswith(".") else "- ")
                    self._preview_insert_inline(widget, prefix + content.strip(), ("pv_list",))
                    widget.insert("end", "\n")
                    i += 1
                    continue

                paragraph = [stripped]
                j = i + 1
                while j < len(lines) and not is_special_line(lines[j]):
                    paragraph.append(lines[j].strip())
                    j += 1
                self._preview_insert_inline(widget, " ".join(paragraph))
                widget.insert("end", "\n\n")
                i = j

            if in_code:
                widget.insert("end", "\n[/code]\n", ("pv_code_fence",))
        except Exception:
            try:
                widget.delete("1.0", "end")
                widget.insert("1.0", src)
            except Exception:
                pass
        finally:
            try:
                widget.configure(state="disabled")
                widget.yview_moveto(yfrac)
            except Exception:
                pass

    def _on_title_change(self):
        if getattr(self, "_loading_tab_state", False):
            return
        doc = self._current_tab_doc()
        if doc is not None and str(self.title_var.get() or "").strip() != doc.get("title", ""):
            self._dirty = True
            self._update_title()
        try:
            self._update_statusbar()
        except Exception:
            pass
        try:
            if self.code_mode.get():
                self._sync_editor_mode_state()
            else:
                self._refresh_run_interpreter()
                self._update_editor_chrome()
                self._update_markdown_preview_visibility()
                self._schedule_preview_update()
        except Exception:
            pass
        try:
            self._sync_active_tab_from_editor()
        except Exception:
            pass

    def _current_run_kind(self) -> str | None:
        ext = self._current_document_suffix()
        if ext == ".py":
            return "python"
        if ext == ".tex":
            return "tex"
        if ext in {".sh", ".command"}:
            return "shell"
        if ext in {".md", ".markdown", ".json", ".yaml", ".yml", ".rs", ".js", ".mjs", ".cjs", ".java", ".bat", ".cmd", ".ps1", ".html", ".htm", ".css", ".php"}:
            return None
        if bool(self.code_mode.get()):
            return "python"
        return None

    def _execution_cwd(self) -> str | None:
        path = getattr(self, "external_file", None)
        if path:
            try:
                return str(Path(path).resolve().parent)
            except Exception:
                return os.path.dirname(path)
        try:
            return os.getcwd()
        except Exception:
            return None

    def _iter_execution_roots(self):
        seen = set()
        candidates = []
        path = getattr(self, "external_file", None)
        if path:
            try:
                candidates.append(Path(path).resolve().parent)
            except Exception:
                candidates.append(Path(os.path.dirname(path)))
        try:
            candidates.append(Path.cwd())
        except Exception:
            pass

        for root in candidates:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            yield root

    def _python_from_env_dir(self, env_dir: str | Path | None) -> str | None:
        if not env_dir:
            return None
        env_path = Path(env_dir).expanduser()
        for rel_bin in ("bin/python", "bin/python3", "Scripts/python.exe", "Scripts/python"):
            cand = env_path / rel_bin
            if cand.exists() and os.access(cand, os.X_OK):
                return str(cand)
        return None

    def _venv_dir_from_interpreter(self, interpreter: str | None) -> Path | None:
        if not interpreter:
            return None
        raw = Path(interpreter).expanduser()
        raw_parent = raw.parent
        if raw_parent.name in {"bin", "Scripts"}:
            raw_env_dir = raw_parent.parent
            if (raw_env_dir / "pyvenv.cfg").exists() or raw_env_dir.name in {".venv", "venv", "env"}:
                return raw_env_dir
        try:
            resolved = Path(interpreter).expanduser().resolve()
        except Exception:
            resolved = Path(interpreter)
        parent = resolved.parent
        if parent.name in {"bin", "Scripts"}:
            env_dir = parent.parent
            if (env_dir / "pyvenv.cfg").exists() or env_dir.name in {".venv", "venv", "env"}:
                return env_dir
        return None

    def _discover_venv_interpreters(self):
        env_names = (".venv", "venv", "env")
        items = []
        seen = set()

        for root_index, root in enumerate(self._iter_execution_roots()):
            for depth, base in enumerate((root, *root.parents)):
                for env_name in env_names:
                    env_dir = base / env_name
                    interp = self._python_from_env_dir(env_dir)
                    if not interp:
                        continue
                    try:
                        resolved = str(Path(interp).expanduser().resolve())
                    except Exception:
                        resolved = str(interp)
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    if not self._python_interpreter_works(resolved):
                        continue
                    items.append(
                        {
                            "interpreter": interp,
                            "env_dir": str(env_dir),
                            "root_index": root_index,
                            "depth": depth,
                            "is_nearest": len(items) == 0,
                        }
                    )
        return items

    def _find_nearest_venv_interpreter(self) -> str | None:
        items = self._discover_venv_interpreters()
        if items:
            return items[0]["interpreter"]
        return None

    def _python_subprocess_env(self, interpreter: str | None = None) -> dict:
        env = os.environ.copy()
        for key in (
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONEXECUTABLE",
            "__PYVENV_LAUNCHER__",
        ):
            env.pop(key, None)

        if interpreter:
            try:
                bin_dir = str(Path(interpreter).expanduser().resolve().parent)
                current_path = env.get("PATH", "")
                parts = [bin_dir]
                if current_path:
                    parts.extend(p for p in current_path.split(os.pathsep) if p)
                deduped = []
                seen = set()
                for part in parts:
                    if part in seen:
                        continue
                    seen.add(part)
                    deduped.append(part)
                env["PATH"] = os.pathsep.join(deduped)
            except Exception:
                pass
        return env

    def _is_valid_python_candidate_path(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        try:
            resolved = str(Path(candidate).expanduser().resolve())
        except Exception:
            resolved = str(candidate)
        if not resolved:
            return False
        if ".app/Contents/MacOS/" in resolved and not Path(resolved).name.startswith("python"):
            return False
        return os.path.exists(resolved) and os.access(resolved, os.X_OK)

    def _python_interpreter_works(self, interpreter: str | None) -> bool:
        if not self._is_valid_python_candidate_path(interpreter):
            return False
        try:
            proc = subprocess.run(
                [interpreter, "-c", "import encodings, sys; print(sys.version_info[0])"],
                capture_output=True,
                text=True,
                timeout=8,
                env=self._python_subprocess_env(interpreter),
            )
            return proc.returncode == 0 and (proc.stdout or "").strip() == "3"
        except Exception:
            return False

    def _format_python_choice_label(self, item: dict) -> str:
        env_dir = item.get("env_dir") or ""
        label = f"{Path(env_dir).name}  —  {env_dir}"
        if item.get("is_nearest"):
            label += "  (nächste)"
        return label

    def _set_python_interpreter_override(self, interpreter: str, *, source_label: str | None = None):
        self._python_interpreter_override = interpreter
        self._run_python_path = None
        try:
            self._refresh_run_interpreter()
        except Exception:
            pass
        try:
            self._update_statusbar()
        except Exception:
            pass
        if source_label:
            self.status_message(source_label)

    def _clear_python_interpreter_override(self):
        self._python_interpreter_override = None
        self._run_python_path = None
        try:
            self._refresh_run_interpreter()
        except Exception:
            pass
        try:
            self._update_statusbar()
        except Exception:
            pass
        self.status_message("Python-venv: Automatik aktiv (nächste passende venv).")

    def _choose_python_venv(self):
        items = self._discover_venv_interpreters()
        win = tk.Toplevel(self)
        win.title("venv auswählen")
        win.transient(self)
        try:
            win.grab_set()
        except Exception:
            pass

        frm = tk.Frame(win, padx=12, pady=12)
        frm.pack(fill="both", expand=True)

        current = self.__dict__.get("_python_interpreter_override")
        info = current or self._resolve_python_interpreter() or "Keine passende Python-Umgebung gefunden"
        tk.Label(
            frm,
            text=f"Aktuell: {info}",
            justify="left",
            anchor="w",
            wraplength=720,
        ).pack(fill="x", pady=(0, 8))

        listbox = tk.Listbox(frm, width=96, height=max(6, min(12, len(items) + 1)))
        listbox.pack(fill="both", expand=True)
        for item in items:
            listbox.insert("end", self._format_python_choice_label(item))

        if items:
            selected_index = 0
            if current:
                for idx, item in enumerate(items):
                    if item["interpreter"] == current:
                        selected_index = idx
                        break
            listbox.selection_set(selected_index)
            listbox.see(selected_index)
        else:
            listbox.insert("end", "Keine passende venv in der Nähe gefunden.")
            listbox.config(state="disabled")

        def _apply_selected():
            if not items:
                return
            sel = listbox.curselection()
            if not sel:
                return
            item = items[sel[0]]
            self._set_python_interpreter_override(
                item["interpreter"],
                source_label=f"Python-venv gewählt: {item['env_dir']}",
            )
            win.destroy()

        def _choose_other():
            env_dir = filedialog.askdirectory(parent=win, title="venv-Ordner wählen")
            if not env_dir:
                return
            interp = self._python_from_env_dir(env_dir)
            if not interp:
                messagebox.showerror("venv auswählen", "Im gewählten Ordner wurde kein Python-Interpreter einer venv gefunden.")
                return
            if not self._python_interpreter_works(interp):
                messagebox.showerror("venv auswählen", "Die gewählte venv ist nicht lauffähig.")
                return
            self._set_python_interpreter_override(
                interp,
                source_label=f"Python-venv gewählt: {env_dir}",
            )
            win.destroy()

        btns = tk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Automatik", command=lambda: (self._clear_python_interpreter_override(), win.destroy())).pack(side="left")
        ttk.Button(btns, text="Andere venv…", command=_choose_other).pack(side="left", padx=6)
        ttk.Button(btns, text="Übernehmen", command=_apply_selected, state=("normal" if items else "disabled")).pack(side="right")
        ttk.Button(btns, text="Abbrechen", command=win.destroy).pack(side="right", padx=6)

        try:
            listbox.bind("<Double-Button-1>", lambda _e: _apply_selected())
            win.wait_window()
        except Exception:
            pass

    def _open_terminal_script(self, shell_command: str, *, title: str = "Terminal öffnen") -> bool:
        escaped = shell_command.replace("\\", "\\\\").replace("\"", "\\\"")
        try:
            proc = subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e", 'tell application "Terminal" to activate',
                    "-e", f'tell application "Terminal" to do script "{escaped}"',
                ],
                capture_output=True,
                text=True,
            )
        except Exception as e:
            messagebox.showerror(title, f"Terminal konnte nicht geöffnet werden:\n{e}")
            return False
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "osascript fehlgeschlagen").strip()
            messagebox.showerror(title, f"Terminal konnte nicht geöffnet werden:\n{msg}")
            return False
        return True

    def _open_path_in_terminal(self):
        cwd = self._execution_cwd()
        if not cwd:
            messagebox.showinfo("Pfad im Terminal öffnen", "Kein Pfad verfügbar.")
            return
        cmd = f"cd {shlex.quote(cwd)} && clear"
        if self._open_terminal_script(cmd, title="Pfad im Terminal öffnen"):
            self.status_message(f"Terminal geöffnet: {cwd}")

    def _open_venv_in_terminal(self):
        interp = self.__dict__.get("_run_python_path") or self._resolve_python_interpreter()
        env_dir = self._venv_dir_from_interpreter(interp)
        if not env_dir:
            messagebox.showinfo("venv im Terminal öffnen", "Aktuell ist keine venv als Python-Umgebung aktiv.")
            return

        activate = env_dir / "bin" / "activate"
        if not activate.exists():
            activate = env_dir / "Scripts" / "activate"

        cmd = f"cd {shlex.quote(str(env_dir))}"
        if activate.exists():
            cmd += f" && source {shlex.quote(str(activate))}"
        cmd += " && clear"

        if self._open_terminal_script(cmd, title="venv im Terminal öffnen"):
            self.status_message(f"venv im Terminal geöffnet: {env_dir}")

    def _build_terminal_exec_command(
        self,
        command: list[str] | str,
        *,
        cwd: str | None = None,
        header: str | None = None,
        target_path: str | None = None,
        env_unset: tuple[str, ...] = (),
        cleanup_path: str | None = None,
    ) -> str:
        parts = []
        if env_unset:
            parts.append("unset " + " ".join(env_unset))
        if cwd:
            parts.append(f"cd {shlex.quote(cwd)}")

        info_lines = []
        if header:
            info_lines.append(header)
        if target_path:
            info_lines.append(f"Datei: {target_path}")
        if cwd:
            info_lines.append(f"Arbeitsordner: {cwd}")
        if info_lines:
            parts.append("printf '%s\\n' " + " ".join(shlex.quote(line) for line in [*info_lines, ""]))

        cmd_text = command if isinstance(command, str) else shlex.join(command)
        parts.append(cmd_text)

        cleanup = f"rm -f {shlex.quote(cleanup_path)}; " if cleanup_path else ""
        parts.append(
            "status=$?; "
            + cleanup
            + "printf '\\nExit-Code: %s\\n' \"$status\""
        )
        return " ; ".join(parts)

    def _build_python_terminal_command(self, interpreter: str, target_path: str, cwd: str | None, is_temp: bool) -> str:
        return self._build_terminal_exec_command(
            [interpreter, target_path],
            cwd=cwd,
            header=f"PY ausführen\nInterpreter: {interpreter}",
            target_path=target_path,
            env_unset=("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__"),
            cleanup_path=(target_path if is_temp else None),
        )

    def _iter_python_interpreter_candidates(self):
        candidates = [
            ("python.org: 3.13", "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"),
            ("python.org: 3.12", "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"),
            ("python.org: 3.11", "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"),
            ("python.org: Current", "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"),
            ("homebrew: /opt/homebrew/bin/python3", "/opt/homebrew/bin/python3"),
            ("homebrew: /usr/local/bin/python3", "/usr/local/bin/python3"),
            ("pyenv: ~/.pyenv/shims/python3", os.path.expanduser("~/.pyenv/shims/python3")),
            ("PATH: python3", shutil.which("python3")),
            ("PATH: python", shutil.which("python")),
            ("system: /usr/bin/python3", "/usr/bin/python3"),
        ]
        seen = set()
        for source, candidate in candidates:
            if not candidate:
                continue
            try:
                resolved = str(Path(candidate).expanduser().resolve())
            except Exception:
                resolved = str(candidate)
            if resolved in seen:
                continue
            seen.add(resolved)
            yield source, resolved

    def _resolve_python_interpreter(self) -> str | None:
        """
        Liefert den Pfad zum Python-Interpreter.
        Bevorzugt die nächstgelegene `venv`/`.venv` relativ zur geöffneten Datei.
        """
        self._run_python_source = None
        try:
            manual_python = self.__dict__.get("_python_interpreter_override")
            if manual_python and self._python_interpreter_works(manual_python):
                env_dir = self._venv_dir_from_interpreter(manual_python)
                self._run_python_source = f"venv manuell: {env_dir or manual_python}"
                return manual_python

            venv_python = self._find_nearest_venv_interpreter()
            if venv_python and self._python_interpreter_works(venv_python):
                self._run_python_source = f"venv: {Path(venv_python).parent.parent}"
                return venv_python

            if not getattr(sys, "frozen", False) and self._python_interpreter_works(sys.executable):
                self._run_python_source = f"aktuell: {sys.executable}"
                return sys.executable

            for source, candidate in self._iter_python_interpreter_candidates():
                if self._python_interpreter_works(candidate):
                    self._run_python_source = source
                    return candidate
            return None
        except Exception:
            return None

    def _resolve_pip_python(self) -> str | None:
        seen = set()
        candidates = [
            self.__dict__.get("_run_python_path"),
            self._resolve_python_interpreter(),
            None if getattr(sys, "frozen", False) else sys.executable,
        ]
        candidates.extend(candidate for _source, candidate in self._iter_python_interpreter_candidates())

        for candidate in candidates:
            if not candidate:
                continue
            try:
                resolved = str(Path(candidate).expanduser().resolve())
            except Exception:
                resolved = str(candidate)
            if resolved in seen:
                continue
            seen.add(resolved)
            if self._python_interpreter_works(resolved):
                return resolved
        return None

    def _python_module_available(self, interpreter: str | None, module: str) -> bool:
        if not self._python_interpreter_works(interpreter):
            return False
        try:
            proc = subprocess.run(
                [
                    interpreter,
                    "-c",
                    f"import importlib.util, sys; sys.stdout.write('1' if importlib.util.find_spec({module!r}) else '0')",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                env=self._python_subprocess_env(interpreter),
            )
            return proc.returncode == 0 and (proc.stdout or "").strip() == "1"
        except Exception:
            return False

    def _resolve_python_with_module(self, module: str) -> str | None:
        seen = set()
        candidates = [
            self.__dict__.get("_run_python_path"),
            self._resolve_python_interpreter(),
            None if getattr(sys, "frozen", False) else sys.executable,
        ]
        candidates.extend(candidate for _source, candidate in self._iter_python_interpreter_candidates())

        for candidate in candidates:
            if not candidate:
                continue
            try:
                resolved = str(Path(candidate).expanduser().resolve())
            except Exception:
                resolved = str(candidate)
            if resolved in seen:
                continue
            seen.add(resolved)
            if self._python_module_available(resolved, module):
                return resolved
        return None

    def _python_install_uses_user_site(self, interpreter: str) -> bool:
        try:
            return not (Path(interpreter).resolve().parent.parent / "pyvenv.cfg").exists()
        except Exception:
            return True

    def _build_python_install_cmd(self, interpreter: str, package: str) -> list[str]:
        cmd = [interpreter, "-m", "pip", "install"]
        if self._python_install_uses_user_site(interpreter):
            cmd.append("--user")
        cmd.append(package)
        return cmd

    def _install_missing_python_package(self, interpreter: str, package: str) -> tuple[int, str]:
        install_cmd = self._build_python_install_cmd(interpreter, package)
        log_parts = []

        def _run(cmd: list[str]):
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self._python_subprocess_env(interpreter),
            )
            log_parts.append(
                f"$ {shlex.join(cmd)}\n\nSTDOUT:\n{proc.stdout or ''}\n\nSTDERR:\n{proc.stderr or ''}\nExit {proc.returncode}"
            )
            return proc

        try:
            proc = _run(install_cmd)
        except Exception as e:
            return -1, f"Fehler beim Starten von {shlex.join(install_cmd)}:\n{e}"

        output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        pip_missing = (
            "No module named pip" in output
            or "No module named ensurepip" in output
            or "pip is not installed" in output.lower()
        )

        if proc.returncode != 0 and pip_missing:
            ensure_cmd = [interpreter, "-m", "ensurepip", "--upgrade"]
            if self._python_install_uses_user_site(interpreter):
                ensure_cmd.append("--user")
            try:
                ensure_proc = _run(ensure_cmd)
            except Exception as e:
                log_parts.append(f"Fehler beim Starten von {shlex.join(ensure_cmd)}:\n{e}")
                ensure_proc = None

            if ensure_proc and ensure_proc.returncode == 0:
                try:
                    proc = _run(install_cmd)
                except Exception as e:
                    log_parts.append(f"Fehler beim erneuten Starten von {shlex.join(install_cmd)}:\n{e}")
                    return -1, "\n\n".join(log_parts)

        return proc.returncode, "\n\n".join(log_parts)

    def _detect_tex_engine(self) -> str:
        try:
            src = self.text.get("1.0", "end-1c")
        except Exception:
            src = ""

        patterns = (
            r"(?im)^\s*%\s*!TEX\s+program\s*=\s*([A-Za-z0-9._+-]+)\s*$",
            r"(?im)^\s*%\s*!TeX\s+TS-program\s*=\s*([A-Za-z0-9._+-]+)\s*$",
        )
        for pattern in patterns:
            match = re.search(pattern, src)
            if match:
                engine = (match.group(1) or "").strip().lower()
                if engine in {"pdflatex", "xelatex", "lualatex"}:
                    return engine
        return "pdflatex"

    
    def _find_binary(self, name: str) -> str | None:
        candidates = [
            "/Library/TeX/texbin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/opt/local/bin",
        ]
        found = shutil.which(name)
        if found:
            return found
        for base in candidates:
            p = os.path.join(base, name)
            if os.path.exists(p) and os.access(p, os.X_OK):
                return p
        return None

    def _build_tex_env(self) -> dict:
        env = os.environ.copy()
        extra = [
            "/Library/TeX/texbin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/opt/local/bin",
        ]
        current = env.get("PATH", "")
        parts = [p for p in extra if p]
        if current:
            parts.append(current)
        env["PATH"] = os.pathsep.join(parts)
        return env

    def _resolve_tex_builder(self) -> tuple[str | None, str]:
        engine = self._detect_tex_engine()

        latexmk = self._find_binary("latexmk")
        engine_bin = self._find_binary(engine)

        if latexmk:
            self._run_tex_engine_path = engine_bin or self._find_binary("pdflatex")
            return latexmk, engine

        for candidate in (engine, "pdflatex", "xelatex", "lualatex"):
            builder = self._find_binary(candidate)
            if builder:
                self._run_tex_engine_path = builder
                return builder, candidate

        self._run_tex_engine_path = None
        return None, engine

    def _build_tex_run_command(self, builder: str, engine: str, path: str) -> list[str]:
        name = Path(builder).name.lower()
        engine_path = getattr(self, "_run_tex_engine_path", None)

        if name == "latexmk":
            if engine == "xelatex":
                cmd = [builder, "-xelatex", "-interaction=nonstopmode", "-synctex=1"]
                if engine_path:
                    cmd.insert(1, f"-xelatex={engine_path} %O %S")
                cmd.append(path)
                return cmd
            if engine == "lualatex":
                cmd = [builder, "-lualatex", "-interaction=nonstopmode", "-synctex=1"]
                if engine_path:
                    cmd.insert(1, f"-lualatex={engine_path} %O %S")
                cmd.append(path)
                return cmd
            cmd = [builder, "-pdf", "-interaction=nonstopmode", "-synctex=1"]
            if engine_path:
                cmd.insert(1, f"-pdflatex={engine_path} %O %S")
            cmd.append(path)
            return cmd

        return [builder, "-interaction=nonstopmode", "-synctex=1", path]

    def _prepare_tex_run_target(self) -> tuple[str | None, str | None, bool]:
        path = getattr(self, "external_file", None)
        if self._is_tex_file_path(path):
            if self._dirty and not self._save_current_to_path(path, notify=False):
                return None, None, False
            return path, str(Path(path).with_suffix(".pdf")), False

        try:
            temp_dir = tempfile.mkdtemp(prefix="maat-tex-")
            tex_path = os.path.join(temp_dir, "document.tex")
            with open(tex_path, "w", encoding="utf-8") as tmp:
                tmp.write(self._compose_text_for_file(tex_path))
            return tex_path, str(Path(tex_path).with_suffix(".pdf")), True
        except Exception as e:
            messagebox.showerror("TEX bauen", f"Konnte Temp-Datei nicht erzeugen:\n{e}")
            return None, None, False

    def _tex_attachment_filetypes(self):
        return [
            ("Bilder & TeX-Anhänge", "*.png *.jpg *.jpeg *.pdf *.svg *.eps *.ps *.tex *.tikz *.pgf *.bib *.bst *.sty *.cls *.csv *.tsv *.txt *.dat"),
            ("Bilder", "*.png *.jpg *.jpeg *.pdf *.svg *.eps *.ps"),
            ("TeX-Quellen", "*.tex *.tikz *.pgf *.sty *.cls"),
            ("Bibliografie", "*.bib *.bst"),
            ("Daten/Text", "*.csv *.tsv *.txt *.dat"),
            ("Alle Dateien", "*.*"),
        ]

    def _ensure_tex_attachment_target(self) -> str | None:
        path = getattr(self, "external_file", None)
        if self._is_tex_file_path(path):
            return path

        hint = self._current_document_hint()
        if not self._is_tex_file_path(hint):
            messagebox.showinfo("TeX-Anhang", "Diese Funktion ist nur für LaTeX-Dateien (`.tex`) gedacht.")
            return None

        if not messagebox.askyesno(
            "TeX-Anhang",
            "Für TeX-Anhänge braucht das Dokument zuerst einen echten `.tex`-Dateipfad.\n\nJetzt als `.tex` speichern?"
        ):
            return None

        self._save_as_file()
        path = getattr(self, "external_file", None)
        if self._is_tex_file_path(path):
            return path

        messagebox.showinfo("TeX-Anhang", "TeX-Anhänge wurden abgebrochen, weil keine `.tex`-Datei gespeichert wurde.")
        return None

    def _tex_attachment_kind_and_dir(self, source_path: str | Path) -> tuple[str, Path]:
        ext = Path(source_path).suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".pdf", ".svg", ".eps", ".ps", ".bmp", ".gif", ".tif", ".tiff", ".webp"}:
            return "graphic", Path("assets/images")
        if ext in {".tex", ".tikz", ".pgf"}:
            return "input", Path("assets/input")
        if ext in {".bib", ".bst"}:
            return "bib", Path("assets/bib")
        if ext in {".sty", ".cls"}:
            return "tex-support", Path("assets/tex")
        if ext in {".csv", ".tsv", ".txt", ".dat"}:
            return "data", Path("assets/data")
        return "file", Path("assets/files")

    def _tex_safe_asset_name(self, source: Path) -> str:
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("._-").lower()
        if not stem:
            stem = "asset"
        suffix = source.suffix.lower()
        return f"{stem}{suffix}"

    def _file_sha256(self, path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(131072)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _copy_tex_attachment_asset(self, source_path: str, tex_path: str) -> Path:
        source = Path(source_path).expanduser().resolve()
        tex_dir = Path(tex_path).expanduser().resolve().parent
        _kind, rel_dir = self._tex_attachment_kind_and_dir(source)
        dest_dir = tex_dir / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        base_name = self._tex_safe_asset_name(source)
        stem = Path(base_name).stem
        suffix = Path(base_name).suffix
        candidate = dest_dir / base_name

        if candidate.exists():
            try:
                if source.samefile(candidate):
                    return candidate
            except Exception:
                pass
            try:
                if self._file_sha256(source) == self._file_sha256(candidate):
                    return candidate
            except Exception:
                pass

            counter = 2
            while True:
                probe = dest_dir / f"{stem}_{counter}{suffix}"
                if not probe.exists():
                    candidate = probe
                    break
                try:
                    if self._file_sha256(source) == self._file_sha256(probe):
                        return probe
                except Exception:
                    pass
                counter += 1

        shutil.copy2(source, candidate)
        return candidate

    def _tex_relative_asset_path(self, asset_path: str | Path, tex_path: str | Path) -> str:
        tex_dir = Path(tex_path).expanduser().resolve().parent
        rel = os.path.relpath(str(asset_path), str(tex_dir))
        return rel.replace(os.sep, "/")

    def _tex_has_package(self, package: str) -> bool:
        try:
            src = self.text.get("1.0", "end-1c")
        except Exception:
            return False
        pat = rf"\\usepackage(?:\[[^\]]*\])?\{{[^}}]*\b{re.escape(package)}\b[^}}]*\}}"
        return re.search(pat, src) is not None

    def _insert_tex_preamble_line(self, line: str) -> bool:
        try:
            src = self.text.get("1.0", "end-1c")
        except Exception:
            return False

        insert_at = 0
        usepackages = list(re.finditer(r"(?m)^\\usepackage(?:\[[^\]]*\])?\{[^}]+\}\s*$", src))
        if usepackages:
            insert_at = usepackages[-1].end()
        else:
            docclass = re.search(r"(?m)^\\documentclass(?:\[[^\]]*\])?\{[^}]+\}\s*$", src)
            if docclass:
                insert_at = docclass.end()
            else:
                begin_doc = re.search(r"(?m)^\\begin\{document\}", src)
                if begin_doc:
                    insert_at = begin_doc.start()

        prefix = "\n" if insert_at and not src[:insert_at].endswith("\n") else ""
        suffix = ""
        if insert_at < len(src) and src[insert_at:insert_at + 1] not in {"", "\n"}:
            suffix = "\n"

        self.text.insert(f"1.0+{insert_at}c", f"{prefix}{line}\n{suffix}")
        return True

    def _ensure_tex_graphicx(self):
        if self._tex_has_package("graphicx"):
            return
        if messagebox.askyesno(
            "TeX-Anhang",
            "Für `\\includegraphics` wird meist `\\usepackage{graphicx}` benötigt.\n\nJetzt automatisch im Vorspann ergänzen?"
        ):
            self._insert_tex_preamble_line("\\usepackage{graphicx}")

    def _build_tex_attachment_snippet(self, source_path: str | Path, rel_path: str) -> str:
        source = Path(source_path)
        kind, _ = self._tex_attachment_kind_and_dir(source)
        slug = re.sub(r"[^a-z0-9]+", "-", source.stem.lower()).strip("-") or "anhang"
        caption = re.sub(r"[_-]+", " ", source.stem).strip() or source.name

        if kind == "graphic":
            lines = []
            if source.suffix.lower() in {".svg", ".eps", ".ps", ".bmp", ".gif", ".tif", ".tiff", ".webp"}:
                lines.append(f"% Hinweis: {source.suffix.lower()} braucht je nach TeX-Engine evtl. zusätzliche Unterstützung oder eine Konvertierung nach PDF/PNG.")
            lines.extend([
                "\\begin{figure}[htbp]",
                "    \\centering",
                f"    \\includegraphics[width=0.9\\linewidth]{{{rel_path}}}",
                f"    \\caption{{{caption}}}",
                f"    \\label{{fig:{slug}}}",
                "\\end{figure}",
            ])
            return "\n".join(lines)

        if kind == "input":
            return f"\\input{{{rel_path}}}"

        if kind == "bib":
            rel_no_ext = rel_path[:-4] if rel_path.lower().endswith(".bib") else rel_path
            return (
                f"% Bibliografie-Datei abgelegt: {rel_path}\n"
                f"% Je nach Setup z.B. \\bibliography{{{rel_no_ext}}} oder \\addbibresource{{{rel_path}}}"
            )

        if kind == "tex-support":
            return f"% TeX-Datei abgelegt: {rel_path}\n% Bei Bedarf im Vorspann einbinden."

        return f"% Datei abgelegt: {rel_path}"

    def _insert_tex_attachment(self):
        tex_path = self._ensure_tex_attachment_target()
        if not tex_path:
            return

        selected = filedialog.askopenfilenames(
            title="TeX-Anhang auswählen",
            filetypes=self._tex_attachment_filetypes(),
        )
        if not selected:
            return

        try:
            if any(self._tex_attachment_kind_and_dir(path)[0] == "graphic" for path in selected):
                self._ensure_tex_graphicx()
        except Exception:
            pass

        snippets = []
        errors = []
        copied = []
        for source_path in selected:
            try:
                asset_path = self._copy_tex_attachment_asset(source_path, tex_path)
                rel_path = self._tex_relative_asset_path(asset_path, tex_path)
                snippets.append(self._build_tex_attachment_snippet(source_path, rel_path))
                copied.append(rel_path)
            except Exception as e:
                errors.append(f"{os.path.basename(source_path)}: {e}")

        if snippets:
            block = "\n\n".join(part.rstrip() for part in snippets if part.strip()).rstrip() + "\n"
            try:
                current_line = self.text.get("insert linestart", "insert lineend")
                if current_line.strip():
                    block = "\n" + block
            except Exception:
                pass
            try:
                self.text.edit_separator()
            except Exception:
                pass
            self.text.insert("insert", block)
            try:
                self.text.edit_separator()
            except Exception:
                pass
            try:
                self.text.see("insert")
            except Exception:
                pass
            try:
                self._schedule_highlight()
                self._update_statusbar()
            except Exception:
                pass
            self.status_message(f"TeX-Anhänge eingefügt: {len(copied)} Datei(en)")

        if errors:
            title = "TeX-Anhang"
            body = "\n".join(errors[:8])
            if len(errors) > 8:
                body += f"\n… und {len(errors) - 8} weitere Fehler"
            if snippets:
                messagebox.showwarning(title, f"Einige Anhänge wurden eingefügt, aber nicht alle:\n\n{body}")
            else:
                messagebox.showerror(title, f"Keine Anhänge konnten eingefügt werden:\n\n{body}")

    def _refresh_run_interpreter(self):
        """Aktualisiert Run-Button und Interpreter passend zum aktuellen Dateityp."""
        kind = self._current_run_kind()
        self._run_kind = kind
        path = self._resolve_python_interpreter() if kind == "python" else None
        self._run_python_path = path
        tex_builder, tex_engine = self._resolve_tex_builder() if kind == "tex" else (None, None)
        self._run_tex_builder = tex_builder
        self._run_tex_engine = tex_engine
        try:
            self._update_editor_chrome()
        except Exception:
            pass
        if hasattr(self, "run_btn"):
            if kind == "python":
                self.run_btn.config(text="PY ausführen ▶", state=("normal" if path else "disabled"))
            elif kind == "tex":
                self.run_btn.config(text="TEX bauen ▶", state=("normal" if tex_builder else "disabled"))
            elif kind == "shell":
                label = "COMMAND ausführen ▶" if self._current_external_suffix() == ".command" else "SH ausführen ▶"
                self.run_btn.config(text=label, state="normal")
            else:
                self.run_btn.config(text="Ausführen ▶", state="disabled")

    def _prepare_python_run_target(self) -> tuple[str | None, bool]:
        path = getattr(self, "external_file", None)
        if self._is_python_file_path(path):
            if self._dirty and not self._save_current_to_path(path, notify=False):
                return None, False
            return path, False

        try:
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
                tmp_path = tmp.name
                tmp.write(self._compose_text_for_file(tmp_path))
            return tmp_path, True
        except Exception as e:
            messagebox.showerror("PY ausführen", f"Konnte Temp-Datei nicht erzeugen:\n{e}")
            return None, False

    def _ensure_execute_permission(self, path: str) -> bool:
        try:
            if os.access(path, os.X_OK):
                return True
        except Exception:
            pass

        should_chmod = messagebox.askyesno(
            "Ausführung erlauben?",
            "Diese Datei darf aktuell noch nicht direkt ausgeführt werden.\n\n"
            f"{path}\n\n"
            "Soll die Ausführung jetzt freigegeben werden?\n"
            "Dabei wird automatisch `chmod +x` gesetzt und die Datei kann danach direkt gestartet werden."
        )
        if not should_chmod:
            self.status_message("Start abgebrochen: Ausführung nicht freigegeben.")
            return False

        try:
            mode = os.stat(path).st_mode
            os.chmod(path, mode | 0o111)
            self.status_message(f"Ausführbar gemacht: {os.path.basename(path)}")
            return True
        except Exception as e:
            messagebox.showerror("chmod", f"Konnte Ausführungsrechte nicht setzen:\n{e}")
            return False

    def _build_shell_run_command(self, path: str) -> list[str]:
        first_line = ""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline().strip()
        except Exception:
            pass

        if first_line.startswith("#!"):
            return [path]
        if path.lower().endswith(".command"):
            return ["/bin/zsh", path]
        return ["/bin/sh", path]

    def _run_shell_file(self):
        path = getattr(self, "external_file", None)
        if not self._is_shell_file_path(path):
            messagebox.showinfo(
                "Skript ausführen",
                "Zum direkten Start bitte zuerst eine `.sh`- oder `.command`-Datei öffnen oder speichern."
            )
            return

        if self._dirty and not self._save_current_to_path(path, notify=False):
            return
        if not self._ensure_execute_permission(path):
            return

        cmd = self._build_shell_run_command(path)
        cwd = self._execution_cwd()

        if getattr(sys, "frozen", False):
            terminal_cmd = self._build_terminal_exec_command(
                cmd,
                cwd=cwd,
                header="Skript ausführen",
                target_path=path,
            )
            if self._open_terminal_script(terminal_cmd, title="Skript im Terminal ausführen"):
                self.status_message("Skript im Terminal gestartet.")
            return

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            rc = proc.returncode
        except Exception as e:
            stdout, stderr, rc = "", str(e), -1

        info = f"Datei: {path}\nBefehl: {' '.join(cmd)}"
        try:
            self._show_run_output(
                path,
                stdout,
                stderr,
                rc,
                title=f"{Path(path).name} – Exit {rc}",
                info=info,
                run_kind="shell",
            )
        except Exception:
            msg = [f"Datei: {path}", f"Exit-Code: {rc}", f"Befehl: {' '.join(cmd)}"]
            if stdout.strip():
                msg.append("\n--- stdout ---\n" + stdout.strip())
            if stderr.strip():
                msg.append("\n--- stderr ---\n" + stderr.strip())
            messagebox.showinfo("Skript – Ergebnis", "\n".join(msg))

    def _run_tex_file(self):
        builder = getattr(self, "_run_tex_builder", None)
        engine = getattr(self, "_run_tex_engine", None) or self._detect_tex_engine()
        if not builder:
            messagebox.showerror("TEX bauen", "Kein LaTeX-Builder gefunden. Installiere z.B. MacTeX bzw. `latexmk`.")
            return

        target_path, pdf_path, is_temp = self._prepare_tex_run_target()
        if not target_path:
            return

        cwd = str(Path(target_path).resolve().parent)
        cmd = self._build_tex_run_command(builder, engine, target_path)

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=self._build_tex_env())
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            rc = proc.returncode
        except Exception as e:
            stdout, stderr, rc = "", str(e), -1

        info_lines = [
            f"Datei: {target_path}",
            f"Builder: {builder}",
            f"Engine: {engine}",
            f"Arbeitsordner: {cwd}",
        ]
        if pdf_path:
            info_lines.append(f"PDF: {pdf_path}")
        if is_temp:
            info_lines.append("Modus: temporäre Datei")

        if pdf_path and os.path.exists(pdf_path):
            self._last_tex_pdf_path = pdf_path
            try:
                self._schedule_preview_update()
            except Exception:
                pass

        try:
            self._show_run_output(
                target_path,
                stdout,
                stderr,
                rc,
                title=f"TEX bauen – Exit {rc}",
                info="\n".join(info_lines),
                run_kind="tex",
            )
        except Exception:
            msg = info_lines + [f"Exit-Code: {rc}"]
            if stdout.strip():
                msg.append("\n--- stdout ---\n" + stdout.strip())
            if stderr.strip():
                msg.append("\n--- stderr ---\n" + stderr.strip())
            messagebox.showinfo("TEX bauen – Ergebnis", "\n".join(msg))

    def _run_python(self):
        """Führt Python-, Shell- oder TeX-Dateien direkt aus dem Notepad aus."""
        kind = self._current_run_kind()
        if kind == "shell":
            self._run_shell_file()
            return
        if kind == "tex":
            self._run_tex_file()
            return

        interp = getattr(self, "_run_python_path", None) or self._resolve_python_interpreter()
        if not interp:
            messagebox.showerror("PY ausführen", "Kein passender Python-Interpreter gefunden.")
            return

        target_path, is_temp = self._prepare_python_run_target()
        if not target_path:
            return

        cwd = self._execution_cwd()

        if getattr(sys, "frozen", False):
            cmd = self._build_python_terminal_command(interp, target_path, cwd, is_temp)
            if self._open_terminal_script(cmd, title="PY ausführen im Terminal"):
                self.status_message("Python im Terminal gestartet.")
            return

        try:
            proc = subprocess.run(
                [interp, target_path],
                capture_output=True,
                text=True,
                cwd=cwd,
                env=self._python_subprocess_env(interp),
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            rc = proc.returncode
        except Exception as e:
            stdout, stderr, rc = "", str(e), -1

        info_lines = [f"Datei: {target_path}", f"Interpreter: {interp}"]
        if getattr(self, "_run_python_source", None):
            info_lines.append(f"Quelle: {self._run_python_source}")
        if cwd:
            info_lines.append(f"Arbeitsordner: {cwd}")
        if is_temp:
            info_lines.append("Modus: temporäre Datei")

        try:
            self._show_run_output(
                target_path,
                stdout,
                stderr,
                rc,
                title=f"PY ausführen – Exit {rc}",
                info="\n".join(info_lines),
                run_kind="python",
            )
        except Exception:
            msg = info_lines + [f"Exit-Code: {rc}"]
            if stdout.strip():
                msg.append("\n--- stdout ---\n" + stdout.strip())
            if stderr.strip():
                msg.append("\n--- stderr ---\n" + stderr.strip())
            messagebox.showinfo("PY ausführen – Ergebnis", "\n".join(msg))

    # ---------------------------------------------------------------------
    # Linter: Helfer zum Aufräumen vorhandener Markierungen
    # ---------------------------------------------------------------------
    def _clear_lint_marks(self):
        """Entfernt alle bisherigen Lint-Markierungen."""
        try:
            self.text.tag_remove("lint_error", "1.0", "end")
            self.text.tag_remove("lint_warning", "1.0", "end")
            self.text.tag_remove("lint_note", "1.0", "end")
        except Exception:
            pass
        # dynamische Hover-Tags & Map löschen
        try:
            if hasattr(self, "_lint_msg_map"):
                for t in list(self._lint_msg_map.keys()):
                    try:
                        self.text.tag_delete(t)
                    except Exception:
                        pass
        except Exception:
            pass
        self._lint_msg_map = {}
        self._lint_results = []

    # ---------------------------------------------------------------------
    # Linter: Line/Col -> Tk-Index
    # ---------------------------------------------------------------------
    def _tk_index_from_linecol(self, line: int, col: int) -> str:
        """
        Flake8 liefert 1-basige line/col; Tk nutzt 1-basige line und 0-basige col.
        """
        line = max(1, int(line))
        col0 = max(0, int(col) - 1)
        return f"{line}.{col0}"

    # ---------------------------------------------------------------------
    # Linter ausführen (flake8) + Markierungen im Editor
    # ---------------------------------------------------------------------
    def _run_linter(self):
        """Flake8 über den aktuellen Editor-Inhalt laufen lassen, Findings markieren und unten listen."""
        import sys, subprocess, tempfile, re

        # Sicherstellen, dass die Linter-UI existiert (nur anzeigen, wenn Code-Modus)
        try:
            self._ensure_linter_ui(show=bool(self.code_mode.get()))
        except Exception:
            pass

        # Temp .py mit deiner Header-Logik erzeugen
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
                tmp_path = tmp.name
                try:
                    data = self._compose_text_for_file(tmp_path)
                except Exception:
                    title = (self.title_var.get() or "").strip()
                    content = self.text.get("1.0", "end-1c")
                    data = (f"# {title}\n\n{content}") if title else content
                tmp.write(data)
        except Exception as e:
            try:
                messagebox.showerror("Linter", f"Konnte Temp-Datei nicht schreiben:\n{e}")
            except Exception:
                pass
            return

        flake8_python = self._resolve_python_with_module("flake8")
        if not flake8_python:
            pip_python = self._resolve_pip_python()
            install_hint = ""
            if pip_python:
                install_hint = "\n\nTipp:\n\n" + shlex.join(self._build_python_install_cmd(pip_python, "flake8"))
            self.status_message("flake8 wurde in keinem gefundenen Python installiert.")
            try:
                messagebox.showwarning(
                    "Linter",
                    "flake8 wurde in keiner gefundenen Python-Umgebung entdeckt."
                    + install_hint,
                )
            except Exception:
                pass
            return

        # --- flake8 robust starten ---
        cmd = [
            flake8_python, "-m", "flake8",
            "--format=%(path)s:%(row)d:%(col)d: %(code)s %(text)s",
            "--max-line-length=120",
            tmp_path
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self._python_subprocess_env(flake8_python),
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
        except Exception as e:
            try:
                messagebox.showerror("Linter", f"flake8 konnte nicht gestartet werden:\n{e}")
            except Exception:
                pass
            return

        if "No module named flake8" in err or "No module named flake8" in out:
            install_hint = shlex.join(self._build_python_install_cmd(flake8_python, "flake8"))
            self.status_message("flake8 fehlt in der gewählten Python-Umgebung.")
            try:
                messagebox.showwarning(
                    "Linter",
                    "flake8 ist in der verwendeten Python-Umgebung nicht installiert.\n\nIm Terminal:\n\n"
                    + install_hint,
                )
            except Exception:
                pass
            return

        # Alte Markierungen entfernen
        self._clear_lint_marks()

        findings = []
        list_items = []

        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(":", 3)
            if len(parts) < 4:
                continue
            _, row_s, col_s, rest = parts
            rest = rest.strip()

            m = re.match(r"^([A-Z]\d+)\s+(.*)$", rest)
            if not m:
                continue
            code, msg = m.groups()
            try:
                row = int(row_s)
                col = int(col_s)
            except ValueError:
                continue

            if code.startswith(("E", "F")):
                tag = "lint_error";   level = "error"
            elif code.startswith("W"):
                tag = "lint_warning"; level = "warning"
            else:
                tag = "lint_note";    level = "note"

            si = self._tk_index_from_linecol(row, col)
            ei = f"{row}.end"

            uniq = f"lint_msg_{len(findings)}"
            try:
                self.text.tag_add(tag, si, ei)
                self.text.tag_add(uniq, si, ei)
            except Exception:
                continue

            if not hasattr(self, "_lint_msg_map"):
                self._lint_msg_map = {}
            self._lint_msg_map[uniq] = f"{code}: {msg}"

            findings.append((tag, si, ei, f"{code}: {msg}", level))
            list_items.append((row, col, code, msg))

        self._lint_results = findings

        if findings:
            n_err = sum(1 for *_, lvl in findings if lvl == "error")
            n_warn = sum(1 for *_, lvl in findings if lvl == "warning")
            n_note = sum(1 for *_, lvl in findings if lvl == "note")
            self.status_message(f"Linter: {n_err} Fehler, {n_warn} Warnungen, {n_note} Hinweise")
            try:
                self.text.see(findings[0][1])
            except Exception:
                pass
        else:
            self.status_message("Linter: keine Probleme ✓")

        if getattr(self, "linter_list", None):
            self.linter_list.delete(0, "end")
            for row, col, code, msg in list_items:
                self.linter_list.insert("end", f"{row}:{col}  {code}  {msg}")

            def _jump_from_list(_evt=None):
                sel = self.linter_list.curselection()
                if not sel:
                    return
                text = self.linter_list.get(sel[0])
                try:
                    head, _ = text.split("  ", 1)
                    row_s, col_s = head.split(":")
                    row = int(row_s); col = int(col_s)
                    idx = self._tk_index_from_linecol(row, col)
                    self.text.mark_set("insert", idx)
                    self.text.see(idx)
                    self.text.focus_set()
                except Exception:
                    pass

            try:
                self.linter_list.unbind("<Double-Button-1>")
                self.linter_list.unbind("<Return>")
            except Exception:
                pass
            self.linter_list.bind("<Double-Button-1>", _jump_from_list)
            self.linter_list.bind("<Return>", _jump_from_list)

###Stabilität
    # --- Menü-Helper: robustes Hinzufügen von Einträgen ---
    def _safe_add_command(self, menu: tk.Menu, **kwargs):
        """
        add_command mit Fallback:
        - versucht normalen add_command
        - bei Fehler: fügt zumindest einen passiven Label-Eintrag hinzu
        """
        try:
            return menu.add_command(**kwargs)
        except Exception as e:
            try:
                label = kwargs.get("label", "")
                print(f"[menu] add_command '{label}' fehlgeschlagen: {e}")
            except Exception:
                pass
            # Fallback: ohne command/accelerator
            try:
                menu.add_command(label=kwargs.get("label", ""))
            except Exception:
                pass
            return None

    def _safe_add_checkbutton(self, menu: tk.Menu, **kwargs):
        """Sicheres add_checkbutton (z.B. für Dunkelmodus)."""
        try:
            return menu.add_checkbutton(**kwargs)
        except Exception as e:
            try:
                label = kwargs.get("label", "")
                print(f"[menu] add_checkbutton '{label}' fehlgeschlagen: {e}")
            except Exception:
                pass
            # Fallback: als normaler Eintrag ohne Funktion
            try:
                menu.add_command(label=kwargs.get("label", ""))
            except Exception:
                pass
            return None

    def _safe_add_radiobutton(self, menu: tk.Menu, **kwargs):
        """Sicheres add_radiobutton."""
        try:
            return menu.add_radiobutton(**kwargs)
        except Exception as e:
            try:
                label = kwargs.get("label", "")
                print(f"[menu] add_radiobutton '{label}' fehlgeschlagen: {e}")
            except Exception:
                pass
            try:
                menu.add_command(label=kwargs.get("label", ""))
            except Exception:
                pass
            return None

    def _safe_add_cascade(self, menubar: tk.Menu, **kwargs):
        """Sicheres add_cascade für Untermenüs."""
        try:
            return menubar.add_cascade(**kwargs)
        except Exception as e:
            try:
                label = kwargs.get("label", "")
                print(f"[menu] add_cascade '{label}' fehlgeschlagen: {e}")
            except Exception:
                pass
            return None


####Ende


    def _show_run_output(self, path, stdout, stderr, rc, *, title=None, info=None, run_kind="python"):
        win = tk.Toplevel(self)
        win.title(title or f"Ausführen – Exit {rc}")
        win.geometry("800x520")
        win.transient(self)
        win.grab_set()

        top = tk.Frame(win, padx=8, pady=8)
        top.pack(fill="x")
        tk.Label(top, text=(info or f"Datei: {path}"), justify="left", anchor="w").pack(side="left")

        btns = tk.Frame(top)
        btns.pack(side="right")

        def copy_all():
            self.clipboard_clear()
            self.clipboard_append(f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n\nEXIT: {rc}")
        ttk.Button(btns, text="Alles kopieren", command=copy_all).pack(side="left", padx=4)
        ttk.Button(btns, text="Schließen", command=win.destroy).pack(side="left", padx=4)

        # --- ModuleNotFound-Erkennung & Hinweis ---
        m = None
        if run_kind == "python":
            m = re.search(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]", stderr) \
                or re.search(r"No module named ['\"]([^'\"]+)['\"]", stderr)
        if m:
            missing_pkg = m.group(1)
            pip_python = self._resolve_pip_python()
            hint_frame = tk.Frame(win, padx=10, pady=6, bg="#FFF7E6", highlightbackground="#F0C36D", highlightthickness=1)
            hint_frame.pack(fill="x", padx=8, pady=(0,8))
            tk.Label(hint_frame, text=f"Fehlendes Modul erkannt: {missing_pkg}", bg="#FFF7E6").pack(anchor="w")

            if pip_python:
                install_cmd = self._build_python_install_cmd(pip_python, missing_pkg)
                cmd_text = shlex.join(install_cmd)
                tk.Label(hint_frame, text=f"Tipp: Installiere mit\n{cmd_text}", bg="#FFF7E6", justify="left").pack(anchor="w", pady=(2,4))
            else:
                install_cmd = None
                cmd_text = ""
                tk.Label(
                    hint_frame,
                    text="Kein geeigneter Python-Interpreter für die Installation gefunden.",
                    bg="#FFF7E6",
                    justify="left",
                ).pack(anchor="w", pady=(2,4))

            def copy_cmd():
                if not install_cmd:
                    return
                self.clipboard_clear()
                self.clipboard_append(cmd_text)
            ttk.Button(
                hint_frame,
                text="Installationsbefehl kopieren",
                command=copy_cmd,
                state=("normal" if install_cmd else "disabled"),
            ).pack(side="left", padx=4)

            def install_now():
                if not install_cmd or not pip_python:
                    messagebox.showerror(
                        "Installation",
                        "Es wurde kein nutzbarer Python-Interpreter für die Paketinstallation gefunden."
                    )
                    return
                if not messagebox.askyesno("Bestätigung", f"Soll das Paket '{missing_pkg}' jetzt installiert werden?"):
                    return
                # Installer-Fenster
                log_win = tk.Toplevel(win)
                log_win.title(f"Installiere {missing_pkg}…")
                log_win.geometry("700x400")
                txt = tk.Text(log_win, wrap="word")
                txt.pack(fill="both", expand=True)
                txt.insert("1.0", f"Starte Installation:\n{cmd_text}\n\nBitte warten…\n")
                txt.config(state="disabled")

                def run_install():
                    rc, out = self._install_missing_python_package(pip_python, missing_pkg)
                    if rc == 0:
                        out = out + "\n\nInstallation erfolgreich."

                    txt.config(state="normal")
                    txt.delete("1.0", "end")
                    txt.insert("1.0", out)
                    txt.config(state="disabled")

                self.after(100, run_install)

            ttk.Button(hint_frame, text="Jetzt installieren", command=install_now).pack(side="left", padx=4)

        # Tabs für STDOUT / STDERR
        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=8, pady=(0,8))

        def make_text(tab_title, content):
            frame = tk.Frame(nb)
            nb.add(frame, text=tab_title)
            y = tk.Scrollbar(frame, orient="vertical")
            y.pack(side="right", fill="y")
            t = tk.Text(frame, wrap="none", yscrollcommand=y.set)
            t.pack(fill="both", expand=True)
            y.config(command=t.yview)
            t.configure(font=("Menlo", 16))
            t.insert("1.0", content if content else "(leer)")
            t.config(state="disabled")

        make_text("STDOUT", stdout)
        make_text("STDERR", stderr)
    #Ende Erkennung PY

    def _insert_tab(self, event=None):
        """Tab-Verhalten: bei Mehrzeilen-Auswahl → Block-Indent, sonst Tab/Spaces einfügen."""
        try:
            if self.text.tag_ranges("sel"):
                # Auswahl vorhanden → prüfen ob mehrzeilig
                a = self.text.index("sel.first linestart")
                b = self.text.index("sel.last lineend")
                if self.text.count(a, b, "lines")[0] >= 1:
                    self._indent_block(1)
                    return "break"
        except Exception:
            pass
        # Einzelcursor → normales Tab
        try:
            self.text.insert("insert", "    ")  # 4 Spaces
        except Exception:
            pass
        return "break"

    def _shift_tab(self, event=None):
        """Shift+Tab → Block-Dedent (so weit möglich)."""
        self._dedent_block(1)
        return "break"


    def _highlight_markdown(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?m)^(#)\s+.+$", src):
            add_match("md_h1", m)
        for m in re.finditer(r"(?m)^(##)\s+.+$", src):
            add_match("md_h2", m)
        for m in re.finditer(r"(?m)^(#{3,6})\s+.+$", src):
            add_match("md_h3", m)
        for m in re.finditer(r"(?ms)^```.*?$.*?^```[ \t]*$", src):
            add_match("md_code", m)
        for m in re.finditer(r"(?m)^```.*$", src):
            add_match("md_fence", m)
        for m in re.finditer(r"`[^`\n]+`", src):
            add_match("md_code", m)
        for m in re.finditer(r"\[[^\]]+\]\([^)]+\)", src):
            add_match("md_link", m)
        for m in re.finditer(r"(?m)^>\s?.*$", src):
            add_match("md_quote", m)
        for m in re.finditer(r"(?m)^\s*(?:[-*+]|\d+\.)\s+.*$", src):
            add_match("md_list", m)
        for m in re.finditer(r"(?m)^\s*(?:---|\*\*\*|___)\s*$", src):
            add_match("md_fence", m)
        for m in re.finditer(r"(\*\*[^*\n]+\*\*|__[^_\n]+__|(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_))", src):
            add_match("md_em", m)

    def _highlight_json(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r'"(?:\\.|[^"\\])*"(?=\s*:)', src):
            add_match("def", m)
        for m in re.finditer(r'"(?:\\.|[^"\\])*"', src):
            add_match("str", m)
        for m in re.finditer(r"\b(?:true|false|null)\b", src, re.I):
            add_match("kw", m)
        for m in re.finditer(r"\b-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\b", src):
            add_match("num", m)

    def _highlight_yaml(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?m)(?<!\\)#.*$", src):
            add_match("com", m)
        for m in re.finditer(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", src):
            add_match("str", m)
        for m in re.finditer(r"(?m)^\s*-\s+", src):
            add_match("dec", m)
        for m in re.finditer(r"(?m)^\s*([A-Za-z0-9_.-]+)\s*:(?=\s|$)", src):
            add_match("def", m, 1)
        for m in re.finditer(r"(?m)(?<=[:]\s)([&*!][^\s#]+)", src):
            add_match("dec", m, 1)
        for m in re.finditer(r"\b(?:true|false|yes|no|on|off|null|~)\b", src, re.I):
            add_match("kw", m)
        for m in re.finditer(r"\b-?(?:0|[1-9]\d*)(?:\.\d+)?\b", src):
            add_match("num", m)

    def _highlight_rust(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?s)/\*.*?\*/|//.*?$", src, re.M):
            add_match("com", m)
        for m in re.finditer(r'r#*"(?:[^"]|"(?=[^#])|(?:"[#]+))*"#*|b?"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])\'', src):
            add_match("str", m)
        for m in re.finditer(r"(?m)^\s*#\[[^\]]+\]", src):
            add_match("dec", m)
        for m in re.finditer(r"\b(?:fn|struct|enum|trait|impl|mod|type|union)\s+([A-Za-z_]\w*)", src):
            add_match("def", m, 1)
        for m in re.finditer(
            r"\b(?:as|async|await|break|const|continue|crate|dyn|else|enum|extern|false|fn|for|if|impl|in|let|"
            r"loop|match|mod|move|mut|pub|ref|return|self|Self|static|struct|super|trait|true|type|unsafe|use|"
            r"where|while)\b",
            src,
        ):
            add_match("kw", m)
        for m in re.finditer(r"(?<!\w)([A-Za-z_]\w*)(?=!\s*(?:\(|\{|$))", src):
            add_match("dec", m, 1)
        for m in re.finditer(r"\b(?:0x[0-9A-Fa-f_]+|0b[01_]+|0o[0-7_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d[\d_]*)?)\b", src):
            add_match("num", m)

    def _highlight_batch(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?im)^\s*(?:rem\b.*|::.*)$", src):
            add_match("com", m)
        for m in re.finditer(r'(?m)"[^"\n]*"', src):
            add_match("str", m)
        for m in re.finditer(r"(?im)^\s*:([A-Za-z0-9_.-]+)\s*$", src):
            add_match("def", m, 1)
        for m in re.finditer(r"%(?:[A-Za-z0-9_]+%|\*|~?[0-9])|![A-Za-z0-9_]+!|%%[A-Za-z]", src):
            add_match("dec", m)
        for m in re.finditer(
            r"(?i)\b(?:assoc|break|call|cd|chcp|choice|cls|copy|del|dir|echo|else|endlocal|erase|exist|exit|for|"
            r"ftype|goto|if|in|mkdir|move|not|pause|popd|pushd|ren|rename|rmdir|set|setlocal|shift|start|title|"
            r"type|where)\b",
            src,
        ):
            add_match("kw", m)
        for m in re.finditer(r"\b\d+\b", src):
            add_match("num", m)

    def _highlight_javascript(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?s)/\*.*?\*/|//.*?$", src, re.M):
            add_match("com", m)
        for m in re.finditer(r"`(?:\\.|[^`\\])*`|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", src):
            add_match("str", m)
        for m in re.finditer(r"@[A-Za-z_]\w*", src):
            add_match("dec", m)
        for m in re.finditer(r"\b(?:class|function)\s+([A-Za-z_$][\w$]*)", src):
            add_match("def", m, 1)
        for m in re.finditer(
            r"\b(?:async|await|break|case|catch|class|const|continue|debugger|default|delete|do|else|export|"
            r"extends|false|finally|for|function|if|import|in|instanceof|let|new|null|of|return|static|super|"
            r"switch|this|throw|true|try|typeof|var|void|while|yield)\b",
            src,
        ):
            add_match("kw", m)
        for m in re.finditer(r"\b(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b", src):
            add_match("num", m)

    def _highlight_java(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?s)/\*.*?\*/|//.*?$", src, re.M):
            add_match("com", m)
        for m in re.finditer(r"'(?:\\.|[^'\\])'|\"(?:\\.|[^\"\\])*\"", src):
            add_match("str", m)
        for m in re.finditer(r"(?m)^\s*@[\w.]+", src):
            add_match("dec", m)
        for m in re.finditer(r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", src):
            add_match("def", m, 1)
        for m in re.finditer(
            r"\b(?:abstract|assert|boolean|break|byte|case|catch|char|class|const|continue|default|do|double|"
            r"else|enum|extends|final|finally|float|for|if|implements|import|instanceof|int|interface|long|"
            r"native|new|null|package|private|protected|public|record|return|short|static|strictfp|super|"
            r"switch|synchronized|this|throw|throws|transient|true|try|var|void|volatile|while)\b",
            src,
        ):
            add_match("kw", m)
        for m in re.finditer(r"\b(?:0[xX][0-9A-Fa-f_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d[\d_]*)?[dDfFlL]?)\b", src):
            add_match("num", m)

    def _highlight_powershell(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?m)#.*$", src):
            add_match("com", m)
        for m in re.finditer(r"'(?:[^']|'')*'|\"(?:[^\"\\]|\\.)*\"", src):
            add_match("str", m)
        for m in re.finditer(r"\$(?:[A-Za-z_][\w:]*|\{[^}]+\})", src):
            add_match("dec", m)
        for m in re.finditer(r"\b(?:function|class|enum|filter)\s+([A-Za-z_][\w-]*)", src, re.I):
            add_match("def", m, 1)
        for m in re.finditer(
            r"\b(?:begin|break|catch|class|continue|do|else|elseif|end|enum|exit|filter|finally|for|foreach|"
            r"function|if|in|param|process|return|switch|throw|trap|try|until|while)\b",
            src,
            re.I,
        ):
            add_match("kw", m)
        for m in re.finditer(r"\b-?(?:0x[0-9A-Fa-f]+|\d+(?:\.\d+)?)\b", src):
            add_match("num", m)

    def _highlight_tex(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?m)(?<!\\)%.*$", src):
            add_match("tex_comment", m)
        for m in re.finditer(r"\\(?:begin|end)\{([^}]+)\}", src):
            add_match("tex_cmd", m, 0)
            if m.lastindex:
                add_match("tex_env", m, 1)
        for m in re.finditer(r"\\[A-Za-z@]+|\\.", src):
            add_match("tex_cmd", m)
        for m in re.finditer(r"(?s)\$\$.*?\$\$|(?<!\\)\$.*?(?<!\\)\$|\\\(.+?\\\)|\\\[.+?\\\]", src):
            add_match("tex_math", m)

    def _highlight_html(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?is)<!--.*?-->", src):
            add_match("com", m)
        for m in re.finditer(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", src):
            add_match("str", m)
        for m in re.finditer(r"(?i)</?\s*([a-z][a-z0-9:-]*)", src):
            add_match("def", m, 1)
        for m in re.finditer(r"(?i)\b([a-z_:][a-z0-9:._-]*)(?=\s*=\s*(?:\"|'|[^\s>]+))", src):
            add_match("kw", m, 1)
        for m in re.finditer(r"\b\d+(?:\.\d+)?\b", src):
            add_match("num", m)

    def _highlight_css(self, src: str):
        def add_match(tag, match, group=0):
            start = match.start(group)
            end = match.end(group)
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        for m in re.finditer(r"(?s)/\*.*?\*/", src):
            add_match("com", m)
        for m in re.finditer(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", src):
            add_match("str", m)
        for m in re.finditer(r"(?m)@[A-Za-z_-][\w-]*", src):
            add_match("dec", m)
        for m in re.finditer(r"(?m)(?:^|[{;]\s*)([A-Za-z_-][\w-]*)(?=\s*:)", src):
            add_match("kw", m, 1)
        for m in re.finditer(r"(?ms)(^|}|;)\s*([^@{}][^{}]*?)\s*\{", src):
            add_match("def", m, 2)
        for m in re.finditer(r"#[0-9A-Fa-f]{3,8}\b|\b\d+(?:\.\d+)?(?:%|[A-Za-z]+)?\b", src):
            add_match("num", m)

    def _highlight_php(self, src: str):
        def add_span(tag, start, end):
            if start == end:
                return
            self.text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")

        self._highlight_html(src)

        php_block_pattern = re.compile(r"(?is)<\?(?:php|=)?[\s\S]*?\?>")
        str_pat = re.compile(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", re.S)
        com_pat = re.compile(r"//.*?$|#.*?$|/\*.*?\*/", re.M | re.S)
        var_pat = re.compile(r"\$[A-Za-z_\x80-\xff][A-Za-z0-9_\x80-\xff]*")
        kw_pat = re.compile(
            r"\b(?:abstract|and|array|as|break|callable|case|catch|class|clone|const|continue|declare|default|do|"
            r"echo|else|elseif|empty|enddeclare|endfor|endforeach|endif|endswitch|endwhile|enum|eval|exit|extends|"
            r"final|finally|fn|for|foreach|function|global|goto|if|implements|include|include_once|instanceof|"
            r"insteadof|interface|isset|match|namespace|new|null|or|print|private|protected|public|readonly|"
            r"require|require_once|return|static|switch|throw|trait|true|false|try|unset|use|var|while|xor|yield)\b",
            re.I,
        )
        def_pat = re.compile(r"\b(?:function|class|interface|trait|enum)\s+([A-Za-z_]\w*)", re.I)
        num_pat = re.compile(r"\b(?:0[xX][0-9a-fA-F]+|\d+\.\d+|\d+)\b")

        for block in php_block_pattern.finditer(src):
            block_src = block.group(0)
            block_offset = block.start()

            for m in re.finditer(r"<\?(?:php|=)?|\?>", block_src, re.I):
                add_span("kw", block_offset + m.start(), block_offset + m.end())
            for m in com_pat.finditer(block_src):
                add_span("com", block_offset + m.start(), block_offset + m.end())
            for m in str_pat.finditer(block_src):
                add_span("str", block_offset + m.start(), block_offset + m.end())
            for m in var_pat.finditer(block_src):
                add_span("dec", block_offset + m.start(), block_offset + m.end())
            for m in kw_pat.finditer(block_src):
                add_span("kw", block_offset + m.start(), block_offset + m.end())
            for m in def_pat.finditer(block_src):
                if m.lastindex:
                    add_span("def", block_offset + m.start(1), block_offset + m.end(1))
            for m in num_pat.finditer(block_src):
                add_span("num", block_offset + m.start(), block_offset + m.end())

    def _highlight_syntax(self):
        """Syntaxhervorhebung für Python, Markdown, JSON, YAML, Rust, JavaScript, Java, Batch, PowerShell, HTML, CSS, PHP und TeX."""
        # Widget evtl. schon zerstört?
        if not hasattr(self, "text") or not str(self.text):
            return
        if not self.code_mode.get():
            return

        try:
            # 1) Alte Tags entfernen
            for t in (
                "kw", "def", "str", "com", "num", "dec",
                "md_h1", "md_h2", "md_h3", "md_em", "md_code", "md_link", "md_quote", "md_list", "md_fence",
                "tex_cmd", "tex_env", "tex_math", "tex_comment",
            ):
                self.text.tag_remove(t, "1.0", "end")

            src = self.text.get("1.0", "end-1c")
            if not src:
                return

            language = self._current_editor_language()
            if language == "markdown":
                self._highlight_markdown(src)
                return
            if language == "json":
                self._highlight_json(src)
                return
            if language == "yaml":
                self._highlight_yaml(src)
                return
            if language == "rust":
                self._highlight_rust(src)
                return
            if language == "javascript":
                self._highlight_javascript(src)
                return
            if language == "java":
                self._highlight_java(src)
                return
            if language == "batch":
                self._highlight_batch(src)
                return
            if language == "powershell":
                self._highlight_powershell(src)
                return
            if language == "html":
                self._highlight_html(src)
                return
            if language == "css":
                self._highlight_css(src)
                return
            if language == "php":
                self._highlight_php(src)
                return
            if language == "tex":
                self._highlight_tex(src)
                return
            if language != "python":
                return

            # 2) Regexe
            # Python Schlüsselwörter
            KW = r"\b(False|None|True|and|as|assert|async|await|break|class|continue|def|del|" \
                r"elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|" \
                r"not|or|pass|raise|return|try|while|with|yield)\b"
            # Funktions-/Klassennamen nach def/class
            DEFNAME = r"\b(?:def|class)\s+([A-Za-z_]\w*)"
            # Strings (einfach/zweifach, auch Triple-Quotes rudimentär)
            STR = r"('''.*?'''|\"\"\".*?\"\"\"|'[^'\n]*'|\"[^\"\n]*\")"
            # Kommentare
            COM = r"#.*"
            # Zahlen
            NUM = r"\b\d+(\.\d+)?\b"
            # Dekoratoren
            DEC = r"(?m)^\s*@\w[\w\.]*"

            def add_tag(tag, it):
                for m in it:
                    s = f"1.0+{m.start()}c"
                    e = f"1.0+{m.end()}c"
                    self.text.tag_add(tag, s, e)

        # 3) Anwenden – Reihenfolge so, dass Strings/Kommentare zuerst “belegt” werden
        #    (damit z.B. Keywords in Kommentaren nicht farbig werden)
            add_tag("str", re.finditer(STR, src, re.S))
            add_tag("com", re.finditer(COM, src))

        # Keywords außerhalb von Strings/Kommentaren:
        # einfache Lösung: trotzdem drüberlegen; für “richtig” müsste man maskieren.
            add_tag("kw", re.finditer(KW, src))

        # Funktions-/Klassennamen (nur den Namen färben, Gruppe 1)
            for m in re.finditer(DEFNAME, src):
                if m.lastindex:
                    s = f"1.0+{m.start(1)}c"
                    e = f"1.0+{m.end(1)}c"
                    self.text.tag_add("def", s, e)

            add_tag("num", re.finditer(NUM, src))
            add_tag("dec", re.finditer(DEC, src))

        except tk.TclError:
            # passiert z.B. wenn währenddessen das Widget zerstört/umgebaut wird
            return
        except Exception:
            # still – Highlighting ist “nice to have”
            return

    def _highlight_current_line(self):
        try:
            self.text.tag_remove("current_line", "1.0", "end")
            line = self.text.index("insert").split(".")[0]
            self.text.tag_add("current_line", f"{line}.0", f"{line}.0 lineend+1c")
            self.text.tag_lower("current_line")
        except Exception:
            pass
    
    def _on_text_modified(self, event=None):
        if getattr(self, "_loading_tab_state", False):
            try:
                self.text.edit_modified(False)
            except Exception:
                pass
            return
        if self.text.edit_modified():
            self._dirty = True
            self.text.edit_modified(False)

            # Syntax-Highlighting neu anstoßen (debounced)
            try:
                self._schedule_highlight()
            except Exception:
                pass
            try:
                self._schedule_preview_update()
            except Exception:
                pass

            # Klammern prüfen + aktuelle Paarmarkierung aktualisieren
            try:
                self._check_brackets_full()
                self._highlight_brace_at_cursor()
            except Exception:
                pass

            # (optional) Fenstertitel/Dirty-Dot aktualisieren
            try:
                self._update_title()
            except Exception:
                pass

            # <<< NEU: Statusleiste sofort aktualisieren
            try:
                self._update_statusbar()
            except Exception:
                pass
            try:
                self._highlight_current_line()
            except Exception:
                pass
            try:
                self._sync_active_tab_from_editor()
            except Exception:
                pass

    def _visible_range(self):
        try:
            start = self.text.index("@0,0")
            bottom_px = self.text.winfo_height()
            end = self.text.index(f"@0,{bottom_px}")
            return start, end
        except Exception:
            return "1.0", "end-1c"

    def _clear_syntax_tags(self, start, end):
        for tag in ("kw","def","str","com","num","dec","md_h1","md_h2","md_h3","md_em","md_code","md_link","md_quote","md_list","md_fence","tex_cmd","tex_env","tex_math","tex_comment"):
            self.text.tag_remove(tag, start, end)

    def _update_header_buttons(self):
        """Passt Save-Buttons je nach 'external_file' an."""
        external_path = getattr(self, "external_file", None)
        language = self._current_editor_language()

        try:
            if hasattr(self, "tex_attach_btn"):
                self.tex_attach_btn.pack_forget()
                if language == "tex":
                    self.tex_attach_btn.pack(side="right", padx=6)
        except Exception:
            pass

        if external_path:
            try:
                self.save_btn.config(text=f"Speichern → {os.path.basename(external_path)}")
            except Exception:
                pass
            try:
                if hasattr(self, "import_btn") and not self.import_btn.winfo_manager():
                    self.import_btn.pack(side="right", padx=6)
            except Exception:
                pass
            self._update_editor_chrome()
            return

        try:
            self.save_btn.config(text="Speichern ⌘S")
        except Exception:
            pass
        try:
            if hasattr(self, "import_btn"):
                self.import_btn.pack_forget()
        except Exception:
            pass
        self._update_editor_chrome()

    def _on_click_save(self):
        """Haupt-Speichern: speichert externe Datei zurück oder normale Notiz."""
        if getattr(self, "external_file", None):
            # zurück in die Originaldatei speichern
            self._save_back_to_external()
        else:
            # normale Notiz speichern
            self._save_note()



    def _save_as_note_from_external(self):
        """Externe Datei als neue Notiz übernehmen (nicht zurück in die Datei)."""
        return self._save_note()

    # ---------- Linenumbers / Scroll ----------
    def _sync_gutter_from_text(self):
        """Scroll- und Gutter-Sync ohne direkte Re-Entrancy im yscrollcommand."""
        try:
            first, last = self.text.yview()
            self.vscroll.set(first, last)
        except Exception:
            return
        try:
            self.linenos.yview_moveto(first)
        except Exception:
            pass
        try:
            self._update_linenumbers()
        except Exception:
            pass

    def _on_yscroll(self, *args):
        """Kompatibilitäts-Hook: nur noch die Scrollbar setzen."""
        try:
            self.vscroll.set(*args)
        except Exception:
            pass

    def _on_scrollbar(self, *args):
        # Scrollbar -> Text
        self.text.yview(*args)
        try:
            self.after_idle(self._sync_gutter_from_text)
        except Exception:
            try:
                self._sync_gutter_from_text()
            except Exception:
                pass


    def _update_linenumbers(self):
        # aktuelle Scrollposition merken (Fraction 0..1)
        try:
            yfrac = float(self.text.yview()[0])
        except Exception:
            yfrac = 0.0

        total = int(self.text.index("end-1c").split('.')[0])
        show_guides = bool(
            getattr(self, "code_mode", None)
            and self.code_mode.get()
            and self._current_editor_language() in {"python", "shell", "tex", "json", "yaml", "rust", "javascript", "java", "batch", "powershell", "html", "css", "php"}
        )

        digits = max(1, len(str(total)))              # Stellen der Zeilennummer
        guide_char = getattr(self, "GUIDE_CHAR", "│") # fallback auf │

        lines = []
        max_level = 0

        if show_guides:
            for i in range(1, total + 1):
                line   = self.text.get(f"{i}.0", f"{i}.end")
                spaces = len(line) - len(line.lstrip(" "))
                level  = max(0, spaces // 4)          # 4-Space-Indent = 1 Level
                max_level = max(max_level, level)
                guides = guide_char * level           # KEIN \n – alles in einer Zeile
                lines.append(f"{i:>{digits}} {guides}")
        else:
            for i in range(1, total + 1):
                lines.append(f"{i:>{digits}}")

        content = "\n".join(lines)

        # Gutterbreite: Ziffern + Leerzeichen + Guide-Level (geclamped)
        width_max = int(getattr(self, "_gutter_width_max", 24))
        desired   = min(digits + 1 + (max_level if show_guides else 0), width_max)
        # nicht kleiner werden lassen als bisher (ruhigeres Layout)
        current   = int(getattr(self, "_gutter_width", 6))
        self._gutter_width = max(current, desired)

        try:
            self.linenos.config(state="normal", wrap="none", width=self._gutter_width)
            self.linenos.delete("1.0", "end")
            self.linenos.insert("1.0", content)
            self.linenos.tag_remove("current_line_no", "1.0", "end")
            try:
                current_line = int(self.text.index("insert").split(".")[0])
                self.linenos.tag_add("current_line_no", f"{current_line}.0", f"{current_line}.end")
            except Exception:
                pass
        finally:
            self.linenos.config(state="disabled")

        # ursprüngliche Scrollposition im Gutter wiederherstellen
        try:
            self.linenos.yview_moveto(yfrac)
        except Exception:
            pass
        self._highlight_current_line()

    def _update_statusbar(self):
        """Aktualisiert Statuszeile mit Dateikontext, Cursorposition und Umfang."""
        try:
            if self.external_file:
                name = os.path.basename(self.external_file)
            else:
                title = self.title_var.get().strip()
                name = title if title else "Notiz ohne Titel"

            content = self.text.get("1.0", "end-1c")
            words = len(content.split())
            chars = len(content)
            line_s, col_s = self.text.index("insert").split(".")
            line = int(line_s)
            col = int(col_s) + 1
            dirty = " • geändert" if self._dirty else ""

            language = self._current_editor_language()
            mode_label = "Code" if self.code_mode.get() else "Notiz"
            language_label = {
                "python": "Python",
                "markdown": "Markdown",
                "json": "JSON",
                "yaml": "YAML",
                "rust": "Rust",
                "javascript": "JavaScript",
                "java": "Java",
                "batch": "Batch",
                "powershell": "PowerShell",
                "html": "HTML",
                "css": "CSS",
                "php": "PHP",
                "tex": "LaTeX",
                "shell": "Shell",
                "text": "Text",
            }.get(language, language.title())
            preview_label = " | Vorschau" if language in {"markdown", "html", "tex"} and bool(self.preview_mode.get()) else ""

            self.status_var.set(
                f"{name}{dirty} | {language_label}{preview_label} | {mode_label} | "
                f"Zeile {line}, Spalte {col} | {words} Wörter, {chars} Zeichen"
            )
        except Exception as e:
            self.status_var.set(f"Fehler in Statusleiste: {e}")
   
########### Helper



    # ---------- Prinzipien-Dialog ----------
    def _choose_principle(self):
        win = tk.Toplevel(self)
        win.title("Prinzipien – Filter")
        win.transient(self); win.grab_set()

        wrapper = tk.Frame(win, padx=12, pady=12)
        wrapper.pack(fill="both", expand=True)

        tk.Label(wrapper, text="Wähle einen Prinzipien‑Filter:").pack(anchor="w", pady=(0,8))

        options = ["Alle"] + PRINCIPLES
        sel = tk.StringVar(value=(self.filter_principle or "Alle"))

        for p in options:
            ttk.Radiobutton(wrapper, text=p, value=p, variable=sel).pack(anchor="w", pady=2)

        btns = tk.Frame(wrapper); btns.pack(fill="x", pady=(12,0))
        def apply():
            choice = sel.get()
            self._set_filter(None if choice == "Alle" else choice)
            win.destroy()
        ttk.Button(btns, text="Abbrechen", command=win.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="OK", command=apply).pack(side="right")

        win.bind("<Return>", lambda e: apply())
        win.bind("<Escape>", lambda e: win.destroy())

    # --- Actions ---
    def _update_save_button_label(self):
        """Aktualisiert den Text des Speichern-Buttons je nach Kontext."""
        try:
            self._update_header_buttons()
        except Exception:
            pass

    def _on_save_clicked(self):
        """Wenn externe Datei geöffnet → gleiche Datei überschreiben, sonst normale Notiz speichern."""
        if getattr(self, "external_file", None):
            self._save_back_to_external()
        else:
            self._save_note()

    def _restore_sashes(self):
        try:
            saved_root = max(200, int(self.ui_state.get("root_sash", 320)))
            self.root_split.sashpos(0, saved_root)
            self._right_split.sashpos(0, int(self.ui_state.get("right_sash", 460)))
            if bool(self.ui_state.get("nav_open", False)):
                self._nav_open()
            else:
                self._nav_close()
        except Exception:
            pass
    def _on_save_click(self):
        """Entscheidet: externe Datei zurückschreiben oder Notiz speichern."""
        if getattr(self, "external_file", None):
            # Speichert in die zuvor geöffnete Datei zurück
            self._save_back_to_external()
        else:
            # Speichert als Notiz (in notes.json etc.)
            self._save_note()

    def _save_back_to_external(self, path: str | None = None):
        """Speichert zur externen Datei (oder zu 'path', wenn angegeben)."""
        if path is None:
            path = getattr(self, "external_file", None)

        if not path:
            messagebox.showinfo("Speichern", "Keine verknüpfte Datei vorhanden.")
            return

        if self._save_current_to_path(path, notify=False):
            self._update_header_buttons()
            try:
                self._analyze()
            except Exception:
                pass
            self._refresh_list()
            self._update_title()
            self._update_statusbar()
            try:
                self._sync_active_tab_from_editor(schedule=False, rebuild=True)
            except Exception:
                pass
            messagebox.showinfo("Gespeichert", f"Zur Datei gespeichert:\n{path}")

    def _capture_sashes(self):
        try:
            current_root = self.root_split.sashpos(0)
            if current_root >= 80:
                self.ui_state["root_sash"] = int(current_root)
            root_sash = int(self.ui_state.get("root_sash", max(200, current_root)))
        except Exception:
            root_sash = int(self.ui_state.get("root_sash", 320))
        try:
            right_sash = self._right_split.sashpos(0)
        except Exception:
            right_sash = 460
        return int(root_sash), int(right_sash)

    def _set_filter(self, name):
        self.filter_principle = name
        self._refresh_list()
        self.title(f"{APP_NAME} – Filter: {name or 'Alle'}")

    def _refresh_list(self):
        notes = self._filtered_notes()
        selected_id = self.current_id
        previous_index = self._select_index()
        self.listbox.delete(0, tk.END)
        selected_index = None
        for idx, note in enumerate(notes):
            title = note.get("title", "(ohne Titel)")
            maat = note.get("maat", 0)
            self.listbox.insert(tk.END, f"{title}  ·  {maat:0.2f}")
            if selected_id is not None and note.get("id") == selected_id:
                selected_index = idx

        if selected_id is not None and selected_index is None and previous_index is not None and previous_index < len(notes):
            selected_index = previous_index

        if selected_index is not None and notes:
            try:
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(selected_index)
                self.listbox.activate(selected_index)
                self.listbox.see(selected_index)
            except Exception:
                pass
        else:
            try:
                self.listbox.selection_clear(0, tk.END)
            except Exception:
                pass
        self._update_filter_hint()

    def _select_index(self):
        sel = self.listbox.curselection()
        if not sel: return None
        return sel[0]

    def _on_select(self, _):
        try:
            if getattr(self, "_note_select_after", None):
                self.after_cancel(self._note_select_after)
        except Exception:
            pass
        self._note_select_after = self.after(180, self._load_selected_note_in_active_tab)

    def _load_selected_note_in_active_tab(self):
        self._note_select_after = None
        idx = self._select_index()
        if idx is None:
            return
        note = self._filtered_notes()[idx]
        existing = self._find_tab_by_note_id(note.get("id"))
        if existing is not None:
            self._activate_tab(existing)
            return
        self._load_note(note)

    def _filtered_notes(self):
        q = (self.search_var.get() or "").strip().lower()
        arr = []
        for n in self.notes:
            if self.filter_principle and self.filter_principle not in (n.get("tags") or []):
                continue
            if q:
                blob = f"{n.get('title','')} {n.get('content','')}".lower()
                if q not in blob:
                    continue
            arr.append(n)
        return self._sorted_notes(arr)

    def _load_note(self, note):
        if not self._maybe_close_current():
            return
        self._replace_active_tab(self._note_to_tab_document(note))

    def _set_scores(self, scores, maat):
        if scores:
            for p in PRINCIPLES:
                self.score_labels[p].set(f"{scores.get(p,0):.1f}")
            self.maat_var.set(f"MAAT: {maat:.2f}")
        else:
            for p in PRINCIPLES:
                self.score_labels[p].set("–")
            self.maat_var.set("MAAT: –")
        if not getattr(self, "_loading_tab_state", False):
            try:
                self._sync_active_tab_from_editor(schedule=False, rebuild=False)
            except Exception:
                pass

    def _new_note(self):
        self._open_document_in_tab(self._blank_tab_document(), reuse_blank=True)
        self.status_message("Neuer Tab geöffnet.")
        return
        


    #Start Notizen
    def _save_note(self):
        # War diese Notiz aus einer extern geöffneten Datei?
        was_external = bool(getattr(self, "external_file", None))

        title = (self.title_var.get() or "").strip() or "(ohne Titel)"
        content = self.text.get("1.0", "end-1c")
        scores, maat = score_text(content)

        top2 = sorted(((p, scores[p]) for p in PRINCIPLES), key=lambda x: x[1], reverse=True)[:2]
        tags = [t[0] for t in top2]

        now = datetime.now().isoformat(timespec="seconds")
        updated_notes = [dict(note) for note in self.notes]
        nid = None if was_external else self.current_id
        if nid is None or not any(n.get("id") == nid for n in updated_notes):
            nid = (max([n.get("id", 0) for n in updated_notes]) + 1) if updated_notes else 1
            note = {
                "id": nid, "title": title, "content": content, "tags": tags,
                "created": now, "updated": now, "scores": scores, "maat": maat,
            }
            updated_notes.append(note)
        else:
            for n in updated_notes:
                if n.get("id") == nid:
                    n.update({
                        "title": title, "content": content, "tags": tags,
                        "updated": now, "scores": scores, "maat": maat,
                    })
                    break

        try:
            save_notes(updated_notes)
        except Exception as exc:
            messagebox.showerror("Speichern", f"Notiz konnte nicht gespeichert werden:\n{exc}")
            return False
        self.notes = updated_notes
        self.current_id = nid
        self.external_file = None
        self._dirty = False
        self._set_scores(scores, maat)
        self._refresh_list()

        if was_external:
            messagebox.showinfo("Übernommen", f"Externe Datei als Notiz übernommen. Tags: {', '.join(tags)}")
            self._dirty = False
            self.external_file = None
            self._update_header_buttons()
        else:
            messagebox.showinfo("Gespeichert", f"Notiz gespeichert. Tags: {', '.join(tags)}")

        # Optional: UI aktualisieren (Titel + Liste)
        try:
            self._update_title()
        except Exception:
            pass
        try:
            self._sync_editor_mode_state()
        except Exception:
            pass
        try:
            self._refresh_list()
        except Exception:
            pass
        try:
            self._sync_active_tab_from_editor(schedule=False, rebuild=True)
        except Exception:
            pass
            #Ende Notizen
        return True

    def _delete_note(self):
        idx = self._select_index()
        notes = self._filtered_notes()
        if idx is None or not (0 <= idx < len(notes)):
            messagebox.showwarning("Löschen", "Bitte zuerst eine Notiz auswählen.")
            return
        note = notes[idx]
        if not messagebox.askyesno(
            "Notiz löschen?",
            f"Notiz '{note.get('title', '(ohne Titel)')}' wirklich löschen?\n"
            "Auch ungespeicherte Änderungen in zugehörigen Tabs werden verworfen.",
            default=messagebox.NO,
        ):
            return
        deleted_id = note.get("id")
        updated_notes = [n for n in self.notes if n.get("id") != deleted_id]
        try:
            save_notes(updated_notes)
        except Exception as exc:
            messagebox.showerror("Löschen", f"Notizen konnten nicht gespeichert werden:\n{exc}")
            return
        self.notes = updated_notes
        remaining_tabs = [doc for doc in self._doc_tabs if doc.get("current_id") != deleted_id]
        removed_before_active = sum(1 for i, doc in enumerate(self._doc_tabs[: max(0, self._active_tab_index)]) if doc.get("current_id") == deleted_id)
        active_removed = bool(self._current_tab_doc() and self._current_tab_doc().get("current_id") == deleted_id)
        self._doc_tabs = remaining_tabs or [self._blank_tab_document()]
        if active_removed:
            self._active_tab_index = max(0, min(self._active_tab_index - removed_before_active, len(self._doc_tabs) - 1))
            self._activate_tab(self._active_tab_index, force=True, persist=False)
        else:
            self._active_tab_index = max(0, min(self._active_tab_index - removed_before_active, len(self._doc_tabs) - 1))
            self._rebuild_tab_bar()
        self._refresh_list()
        self._persist_main_ui_state()

    #Klammer Erkennung
    def _check_brackets_full(self):
        """
        Scannt den gesamten Text und markiert alle fehlerhaften/fehlenden Klammern.
        Unterstützt (), [], {}. Einfacher Parser ohne String-/Kommentarlogik.
        """
        self.text.tag_remove("brace_error", "1.0", "end")

        text = self.text.get("1.0", "end-1c")
        opens = "([{"
        closes = ")]}"
        match_for_close = {')': '(', ']': '[', '}': '{'}
        stack = []  # (open_char, offset)

        def idx(off: int) -> str:
            # Nutze deine vorhandene Helper-Methode, sonst Fallback
            if hasattr(self, "_index_from_offset"):
                return self._index_from_offset(off)
            return f"1.0+{off}c"

        for i, ch in enumerate(text):
            if ch in opens:
                stack.append((ch, i))
            elif ch in closes:
                if not stack or stack[-1][0] != match_for_close[ch]:
                    s = idx(i); e = idx(i+1)
                    self.text.tag_add("brace_error", s, e)
                else:
                    stack.pop()

        # Übrig gebliebene öffnende Klammern -> Fehler
        for ch, i in stack:
            s = idx(i); e = idx(i+1)
            self.text.tag_add("brace_error", s, e)


    def _highlight_brace_at_cursor(self, event=None):
        """
        Hebt das Klammer-Paar an der Cursorposition hervor (nur 1 Paar).
        """
        self.text.tag_remove("brace_match", "1.0", "end")
        try:
            i = self.text.index("insert")
            left  = self.text.get(f"{i} -1c")
            right = self.text.get(i)
            if left in "([{)]}":
                self._highlight_brace_pair_at_index(self.text.index(f"{i} -1c"))
            elif right in "([{)]}":
                self._highlight_brace_pair_at_index(i)
        except Exception:
            pass


    def _highlight_brace_pair_at_index(self, index: str):
        """
        Findet zum Zeichen an 'index' die Partnerklammer und markiert beide.
        """
        ch = self.text.get(index)
        opens = "([{"
        closes = ")]}"
        pairs = {'(' : ')', '[': ']', '{': '}', ')': '(', ']': '[', '}': '{'}

        if ch not in opens + closes:
            return

        forward = ch in opens
        target = pairs[ch]
        depth = 0

        cur  = self.text.index(f"{index} {'+1c' if forward else '-1c'}")
        step = "+1c" if forward else "-1c"

        while True:
            # Ende/Anfang erreicht?
            if forward:
                if self.text.compare(cur, ">=", "end-1c"):
                    return
            else:
                if self.text.compare(cur, "<=", "1.0"):
                    return

            c = self.text.get(cur)
            if forward:
                if c == ch:
                    depth += 1
                elif c == target:
                    if depth == 0:
                        self.text.tag_add("brace_match", index, self.text.index(f"{index} +1c"))
                        self.text.tag_add("brace_match", cur,   self.text.index(f"{cur} +1c"))
                        self.text.see(index); self.text.see(cur)
                        return
                    else:
                        depth -= 1
            else:
                if c == ch:
                    depth += 1
                elif c == target:
                    if depth == 0:
                        self.text.tag_add("brace_match", cur,   self.text.index(f"{cur} +1c"))
                        self.text.tag_add("brace_match", index, self.text.index(f"{index} +1c"))
                        self.text.see(index); self.text.see(cur)
                        return
                    else:
                        depth -= 1

            cur = self.text.index(f"{cur} {step}")
            #Klammer Erkennung Ende

    def _analyze(self):
        content = self.text.get("1.0", tk.END)
        scores, maat = score_text(content)
        self._set_scores(scores, maat)

    def _export_json(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if not path: return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.notes, f, indent=2, ensure_ascii=False)
        messagebox.showinfo("Export", "Export abgeschlossen.")

    def _import_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON","*.json"),("Alle","*.*")])
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("Erwartet wird eine Liste von Notizen.")
            imported = []
            next_id = max((n.get("id", 0) for n in self.notes), default=0) + 1
            now = datetime.now().isoformat(timespec="seconds")
            for index, item in enumerate(data):
                if not isinstance(item, dict) or not isinstance(item.get("content"), str) or not isinstance(item.get("title", ""), str):
                    raise ValueError(f"Notiz {index + 1}: Titel und Inhalt müssen Text sein.")
                scores, maat = score_text(item["content"])
                imported.append({
                    "id": next_id + index, "title": item.get("title") or "(ohne Titel)",
                    "content": item["content"], "created": now, "updated": now,
                    "scores": scores, "maat": maat,
                    "tags": sorted(scores, key=scores.get, reverse=True)[:2],
                })
            if not imported:
                return
            if not messagebox.askyesno("Notizen importieren", f"{len(imported)} Notizen hinzufügen?\nBestehende Notizen bleiben erhalten."):
                return
            updated_notes = self.notes + imported
            save_notes(updated_notes)
            self.notes = updated_notes
            self._refresh_list()
            messagebox.showinfo("Import", "Import abgeschlossen.")
        except Exception as e:
            messagebox.showerror("Import", f"Fehler beim Import: {e}")

    def _compose_text_for_file(self, path: str) -> str:
        """Erstellt den zu speichernden Text und hält Python-Header idempotent."""
        ext = Path(path).suffix.lower()
        title = (self.title_var.get() or "").strip()
        content = self.text.get("1.0", "end-1c")

        if ext != ".py":
            return content

        header = f"# {title}" if title else "#"
        lines = content.splitlines()
        shebang = None
        start_ix = 0

        if lines and lines[0].startswith("#!"):
            shebang = lines[0]
            start_ix = 1

        if start_ix < len(lines) and lines[start_ix].strip() == header:
            if shebang is not None:
                result = "\n".join([shebang] + lines[1:])
                if content.endswith("\n"):
                    result += "\n"
                return result
            return content

        new_lines = []
        if shebang is not None:
            new_lines.append(shebang)
        new_lines.append(header)

        if start_ix < len(lines):
            new_lines.append("")
            new_lines.extend(lines[start_ix:])

        result = "\n".join(new_lines)
        if content.endswith("\n"):
            result += "\n"
        return result

    def _save_current_to_path(self, path: str, notify: bool = True):
        """Speichert den aktuellen Editor-Inhalt auf path (mit .py-Titellogik)."""
        try:
            data = self._compose_text_for_file(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
            self._dirty = False
            try:
                self._sync_active_tab_from_editor(schedule=False, rebuild=True)
            except Exception:
                pass
            if notify:
                messagebox.showinfo("Gespeichert", f"Datei gespeichert:\n{path}")
            self.status_message(f"Datei gespeichert: {os.path.basename(path)}")
            return True
        except Exception as e:
            messagebox.showerror("Speichern", f"Konnte Datei nicht speichern:\n{e}")
            return False

    def _update_title(self):
        """Fenstertitel konsistent mit Datei-/Notizkontext und Dirty-Status halten."""
        try:
            if self.external_file:
                name = os.path.basename(self.external_file)
            else:
                name = (self.title_var.get() or "").strip() or "Unbenannte Notiz"
            dirty = " *" if self._dirty else ""
            self.title(f"{APP_NAME} – {name}{dirty}")
        except Exception:
            pass



    def _on_close(self):
        """Fenster schließen – fragt ggf. nach Speichern und persistiert UI-Status."""
        # Check every document, including edits in inactive tabs.
        try:
            self._sync_active_tab_from_editor(schedule=False, rebuild=False)
            original_index = self._active_tab_index
            for index in range(len(self._doc_tabs)):
                if self._doc_tabs[index].get("dirty"):
                    self._activate_tab(index, persist=False)
                    if not self._maybe_close_current():
                        return
                    self._sync_active_tab_from_editor(schedule=False, rebuild=False)
            self._activate_tab(original_index, persist=False)
        except Exception as exc:
            messagebox.showerror("Beenden", f"Dokumente konnten nicht gesichert werden:\n{exc}")
            return

        # 2) Sash-Positionen ermitteln
        try:
            if hasattr(self, "_capture_sashes"):
                root_sash, right_sash = self._capture_sashes()
            else:
                try:
                    root_sash = self.root_split.sashpos(0)
                except Exception:
                    root_sash = self.ui_state.get("root_sash", 320)
                try:
                    right_sash = self._right_split.sashpos(0)
                except Exception:
                    right_sash = self.ui_state.get("right_sash", 460)
        except Exception:
            root_sash = int(self.ui_state.get("root_sash", 320))
            right_sash = int(self.ui_state.get("right_sash", 460))

        # 3) UI-State persistieren
        try:
            if not self._persist_main_ui_state(root_sash=root_sash, right_sash=right_sash):
                messagebox.showerror("Beenden", "Die Sitzung konnte nicht gespeichert werden. Das Fenster bleibt geöffnet.")
                return
        except Exception as exc:
            messagebox.showerror("Beenden", f"Die Sitzung konnte nicht gespeichert werden:\n{exc}")
            return

        try:
            self._close_native_html_webview()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


    def _save_as_file(self):
        # Basisname aus Titel (ohne Extension) vorschlagen
        suggested = (self.title_var.get() or "Notiz").strip() or "Notiz"
        initial_name = Path(suggested).stem

        path = filedialog.asksaveasfilename(
            initialfile=initial_name,
            defaultextension=".txt",
            filetypes=[
                ("Rust", "*.rs"),
                ("JavaScript", "*.js *.mjs *.cjs"),
                ("Java", "*.java"),
                ("Batch", "*.bat *.cmd"),
                ("PowerShell", "*.ps1"),
                ("Python", "*.py"),
                ("JSON", "*.json"),
                ("YAML", "*.yaml *.yml"),
                ("HTML", "*.html *.htm"),
                ("CSS", "*.css"),
                ("PHP", "*.php"),
                ("LaTeX", "*.tex"),
                ("Shell", "*.sh"),
                ("Command", "*.command"),
                ("Text", "*.txt"),
                ("Markdown", "*.md *.markdown"),
                ("Alle Dateien", "*.*")
            ]
        )
        if not path:
            return

        try:
            if not self._save_current_to_path(path, notify=False):
                return

            # Diese Datei als „extern“ merken, damit der Modus sofort korrekt erkannt wird
            self.external_file = path
            self.current_id = None

            # Optional: Code‑Modus für Skriptdateien
            if self._is_code_file_path(path) and not self.code_mode.get():
                self.code_mode.set(True)
                self._toggle_code_mode()
            try:
                self._sync_editor_mode_state()
            except Exception:
                pass

            self._update_header_buttons()
            self._update_title()
            try:
                self._sync_active_tab_from_editor(schedule=False, rebuild=True)
            except Exception:
                pass

            messagebox.showinfo("Speichern unter", f"Datei gespeichert:\n{path}")
        except Exception as e:
            messagebox.showerror("Speichern unter", f"Fehler: {e}")

    # --- Suche (modelless) ---
    def _open_find(self):
        # Dialog
        win = tk.Toplevel(self)
        win.title("Suchen")
        win.transient(self)   # NICHT grab_set → Editor bleibt benutzbar
        win.resizable(False, False)

        frm = tk.Frame(win, padx=10, pady=10); frm.pack(fill="both", expand=True)

        tk.Label(frm, text="Suchbegriff:").grid(row=0, column=0, sticky="w")
        q_var = tk.StringVar(value=self._last_find.get("q",""))
        ent = tk.Entry(frm, textvariable=q_var, width=36)
        ent.grid(row=0, column=1, columnspan=3, sticky="we", pady=(0,6))
        ent.focus_set(); ent.icursor("end")
        ent.config(insertbackground="black", insertwidth=2, insertontime=600, insertofftime=300)

        case_var  = tk.BooleanVar(value=self._last_find.get("case", False))
        regex_var = tk.BooleanVar(value=self._last_find.get("regex", False))
        tk.Checkbutton(frm, text="Groß/Kleinschreibung", variable=case_var).grid(row=1, column=1, sticky="w")
        tk.Checkbutton(frm, text="Regex", variable=regex_var).grid(row=1, column=2, sticky="w")

        def do_find_all():
            self._apply_find_all(q_var.get(), bool(case_var.get()), bool(regex_var.get()))

        def do_next():
            self._apply_find_move(q_var.get(), bool(case_var.get()), bool(regex_var.get()), forward=True)

        def do_prev():
            self._apply_find_move(q_var.get(), bool(case_var.get()), bool(regex_var.get()), forward=False)

        tk.Button(frm, text="Alle markieren", command=do_find_all).grid(row=2, column=0, pady=(8,0))
        tk.Button(frm, text="Vorheriges (⇧⌘G)", command=do_prev).grid(row=2, column=1, pady=(8,0))
        tk.Button(frm, text="Nächstes (⌘G/Enter)", command=do_next).grid(row=2, column=2, pady=(8,0))
        tk.Button(frm, text="Schließen", command=win.destroy).grid(row=2, column=3, pady=(8,0))

        # Enter/Shift+Enter im Eingabefeld
        ent.bind("<Return>", lambda e: (do_next(), "break"))
        ent.bind("<Shift-Return>", lambda e: (do_prev(), "break"))

    def _apply_find_all(self, q, case, regex):
        self._last_find.update({"q":q, "case":case, "regex":regex})
        self.text.tag_remove("find_all", "1.0", "end")
        self.text.tag_remove("find_current", "1.0", "end")
        if not q:
            self.status_message("Suche: –")
            return

        txt = self.text.get("1.0", "end-1c")
        flags = 0 if case else re.IGNORECASE
        spans = []

        if regex:
            try:
                pat = re.compile(q, flags)
            except re.error as e:
                self.status_message(f"Regex-Fehler: {e}")
                return
            for m in pat.finditer(txt):
                spans.append((m.start(), m.end()))
        else:
            needle = q if case else q.lower()
            hay = txt if case else txt.lower()
            start = 0
            while True:
                i = hay.find(needle, start)
                if i < 0: break
                spans.append((i, i+len(needle)))
                start = i + max(1, len(needle))

        # taggen
        for s, e in spans:
            si = self._index_from_offset(s)
            ei = self._index_from_offset(e)
            self.text.tag_add("find_all", si, ei)

        self.status_message(f"Suche: {len(spans)} Treffer")
        if spans:
            si = self._index_from_offset(spans[0][0])
            ei = self._index_from_offset(spans[0][1])
            self.text.tag_add("find_current", si, ei)
            self.text.mark_set("insert", ei)
            self.text.see(si)   # automatisch hinscrollen

    def _find_next(self):
        q = (self._last_find.get("q") or "").strip()
        if not q:
            try:
                q = self.text.get("sel.first", "sel.last")
                self._last_find["q"] = q
            except Exception:
                self._open_find()
                return
        case  = bool(self._last_find.get("case", False))
        regex = bool(self._last_find.get("regex", False))
        self._apply_find_all(q, case, regex)
        self._apply_find_move(q, case, regex, forward=True)

    def _find_prev(self):
        q = (self._last_find.get("q") or "").strip()
        if not q:
            try:
                q = self.text.get("sel.first", "sel.last")
                self._last_find["q"] = q
            except Exception:
                self._open_find()
                return
        case  = bool(self._last_find.get("case", False))
        regex = bool(self._last_find.get("regex", False))
        self._apply_find_all(q, case, regex)
        self._apply_find_move(q, case, regex, forward=False)

    def _apply_find_move(self, q, case, regex, forward=True):
        if q != self._last_find.get("q") or case != self._last_find.get("case") or regex != self._last_find.get("regex"):
            self._apply_find_all(q, case, regex)

        ranges = self.text.tag_ranges("find_all")
        if not ranges:
            self.status_message("Suche: 0 Treffer")
            return

        items = [(str(ranges[i]), str(ranges[i+1])) for i in range(0, len(ranges), 2)]
        cur = self.text.index("insert")

        idx = 0
        if forward:
            for i,(si,_) in enumerate(items):
                if self.text.compare(si, ">=", cur):
                    idx = i; break
            else:
                idx = 0
        else:
            for i in range(len(items)-1, -1, -1):
                if self.text.compare(items[i][1], "<=", cur):
                    idx = i; break
            else:
                idx = len(items)-1

        self.text.tag_remove("find_current", "1.0", "end")
        si, ei = items[idx]
        self.text.tag_add("find_current", si, ei)
        self.text.mark_set("insert", ei if forward else si)
        self.text.see(si)   # automatisch scrollen
        self.status_message(f"Treffer {idx+1}/{len(items)}")

    def _open_replace(self):
        win = tk.Toplevel(self)
        win.title("Ersetzen")
        win.transient(self)   # kein grab_set → Editor bleibt benutzbar
        win.resizable(False, False)

        frm = tk.Frame(win, padx=10, pady=10)
        frm.pack(fill="both", expand=True)

        # --- Suchfeld ---
        tk.Label(frm, text="Suchen:").grid(row=0, column=0, sticky="w")
        find_var = tk.StringVar(value=self._last_find.get("q", ""))
        find_ent = tk.Entry(frm, textvariable=find_var, width=36)
        find_ent.grid(row=0, column=1, columnspan=3, sticky="we", pady=(0, 6))

        # --- Ersetzen-Feld ---
        tk.Label(frm, text="Ersetzen durch:").grid(row=1, column=0, sticky="w")
        repl_var = tk.StringVar()
        repl_ent = tk.Entry(frm, textvariable=repl_var, width=36)
        repl_ent.grid(row=1, column=1, columnspan=3, sticky="we", pady=(0, 6))

        # Cursor-Style (Blink) für beide Eingaben
        try:
            find_ent.config(insertbackground="black", insertwidth=2, insertontime=600, insertofftime=300)
            repl_ent.config(insertbackground="black", insertwidth=2, insertontime=600, insertofftime=300)
        except Exception:
            pass

        # --- Optionen ---
        case_var = tk.BooleanVar(value=self._last_find.get("case", False))
        regex_var = tk.BooleanVar(value=self._last_find.get("regex", False))
        tk.Checkbutton(frm, text="Groß/Kleinschreibung", variable=case_var).grid(row=2, column=1, sticky="w")
        tk.Checkbutton(frm, text="Regex", variable=regex_var).grid(row=2, column=2, sticky="w")

        # --- Logik ---
        def do_find(forward=True):
            self._apply_find_move(find_var.get(), bool(case_var.get()), bool(regex_var.get()), forward=forward)

        def do_replace():
            if not self.text.tag_ranges("find_current"):
                do_find(True)
            if self.text.tag_ranges("find_current"):
                si, ei = self.text.tag_ranges("find_current")
                self.text.delete(si, ei)
                self.text.insert(si, repl_var.get())
                self.text.mark_set("insert", f"{si}+{len(repl_var.get())}c")
                self.text.see(si)  # hinscrollen
                do_find(True)

        def do_replace_all():
            q = find_var.get()
            r = repl_var.get()
            if not q:
                return
            self._apply_find_all(q, bool(case_var.get()), bool(regex_var.get()))
            ranges = list(self.text.tag_ranges("find_all"))
            if not ranges:
                return
            # von hinten nach vorne ersetzen, damit Indizes stabil bleiben
            for i in range(len(ranges) - 2, -1, -2):
                si, ei = ranges[i], ranges[i + 1]
                self.text.delete(si, ei)
                self.text.insert(si, r)
            self.text.see("1.0")  # nach Replace-All zum Anfang springen
            self.status_message(f"Ersetzen: {len(ranges)//2} Vorkommen")

        # --- Buttons ---
        tk.Button(frm, text="Vorheriges", command=lambda: do_find(False)).grid(row=3, column=0, pady=(8, 0))
        tk.Button(frm, text="Nächstes",   command=lambda: do_find(True)).grid(row=3, column=1, pady=(8, 0))
        tk.Button(frm, text="Ersetzen",   command=do_replace).grid(row=3, column=2, pady=(8, 0))
        tk.Button(frm, text="Alle ersetzen", command=do_replace_all).grid(row=3, column=3, pady=(8, 0))
        tk.Button(frm, text="Schließen", command=win.destroy).grid(row=4, column=3, pady=(8, 0))

        # --- Tastenkürzel ---
        win.bind("<Return>", lambda e: do_find(True))                 # Enter = Nächstes
        win.bind("<Shift-Return>", lambda e: do_find(False))          # Shift+Enter = Vorheriges
        win.bind("<Command-Return>", lambda e: do_replace())          # ⌘Enter = Ersetzen
        win.bind("<Option-Return>", lambda e: do_replace_all())       # ⌥Enter = Alle ersetzen
        win.bind("<Escape>", lambda e: win.destroy())                 # ESC = Schließen

        # Startfokus
        find_ent.focus_set()


    # --- Hilfen ---
    def _index_from_offset(self, off):
        """Offset (0-basiert) → Tk-Index 'line.col'."""
        return f"1.0+{off}c"

    def status_message(self, msg):
        try:
            self.status_var.set(msg)
        except Exception:
            pass
        try:
            if getattr(self, "_status_timer", None):
                self.after_cancel(self._status_timer)
            self._status_timer = self.after(3500, self._update_statusbar)
        except Exception:
            pass
            #Ende Suche


    def _maybe_close_current(self):
        """
        Fragt bei ungespeicherten Änderungen, wie verfahren werden soll.
        Rückgabe: True = weiter; False = abbrechen.
        """
        if not self._dirty:
            return True

        if self.external_file:
            resp = messagebox.askyesnocancel(
                "Änderungen speichern?",
                f"Änderungen an dieser Datei speichern?\n{self.external_file}\n\n"
                "Ja = In der Originaldatei speichern\n"
                "Nein = Verwerfen\n"
                "Abbrechen = Zurück"
            )
            if resp is None:
                return False  # Abbrechen
            if resp is True:
                if not self._save_current_to_path(self.external_file, notify=False):
                    return False
                self._update_statusbar()
                return True
            # resp is False → verwerfen
            if not self._revert_active_document():
                return False
            self._update_statusbar()
            return True
        else:
            # Normale Notiz → Standardfrage
            resp = messagebox.askyesnocancel(
                "Ungespeicherte Änderungen",
                "Möchtest du die Änderungen an dieser Notiz speichern?\n\n"
                "Ja = Speichern\n"
                "Nein = Verwerfen\n"
                "Abbrechen = Zurück"
            )
            if resp is None:
                return False
            if resp is True:
                if not self._save_note():
                    return False
                self._update_statusbar()
                return True
            # Verwerfen
            if not self._revert_active_document():
                return False
            self._update_statusbar()
            return True
            #Ende Abfrage Speichern Notiz

    def _open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Rust", "*.rs"),
                ("JavaScript", "*.js *.mjs *.cjs"),
                ("Java", "*.java"),
                ("Batch", "*.bat *.cmd"),
                ("PowerShell", "*.ps1"),
                ("Python", "*.py"),
                ("JSON", "*.json"),
                ("YAML", "*.yaml *.yml"),
                ("HTML", "*.html *.htm"),
                ("CSS", "*.css"),
                ("PHP", "*.php"),
                ("LaTeX", "*.tex"),
                ("Shell", "*.sh"),
                ("Command", "*.command"),
                ("Text", "*.txt"),
                ("Markdown", "*.md *.markdown"),
                ("Alle Dateien", "*.*")
            ]
        )
        if not path:
            return
        try:
            existing = self._find_tab_by_external_path(path)
            if existing is not None:
                self._activate_tab(existing)
                return
            content = self._read_text_file_with_fallback(path)
        except Exception as e:
            messagebox.showerror("Öffnen", f"Kann Datei nicht lesen:\n{e}")
            return
        self._open_document_in_tab(self._external_to_tab_document(path, content), reuse_blank=True)
        try:
            self.listbox.selection_clear(0, tk.END)
        except Exception:
            pass
        self._update_statusbar()
 
    def _open_file_assoc(self):
        """Dialog: Dateiendungen mit MAAT Notepad verknüpfen (macOS)."""
        win = tk.Toplevel(self)
        win.title("Dateiformate verlinken (macOS)")
        win.transient(self)
        win.resizable(False, False)
        try:
            win.grab_set()  # modal
        except Exception:
            pass

        frm = tk.Frame(win, padx=12, pady=12)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm, text="Diese Dateiendungen mit MAAT Notepad verknüpfen:"
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        # gespeicherte bzw. Default-Endungen
        defaults = list(self._default_file_association_exts())
        saved = list(self.ui_state.get("file_associations", defaults))
        for x in saved:
            if x not in defaults:
                defaults.append(x)

        # Checkboxen im 3-Spalten-Grid
        vars_by_ext = {}
        for i, ext in enumerate(defaults):
            v = tk.BooleanVar(value=(ext in saved))
            vars_by_ext[ext] = v
            r = 1 + (i // 3)
            c = i % 3
            ttk.Checkbutton(frm, text=ext, variable=v).grid(row=r, column=c, sticky="w", padx=(0, 16))

        # Eigene Endung hinzufügen
        next_row = 1 + (len(defaults) // 3) + 1
        tk.Label(frm, text="Eigene Endung hinzufügen (ohne Punkt):").grid(row=next_row, column=0, sticky="w", pady=(10, 0))
        add_var = tk.StringVar()
        add_entry = tk.Entry(frm, textvariable=add_var, width=16)
        add_entry.grid(row=next_row, column=1, sticky="w", pady=(10, 0))
        add_msg = tk.Label(frm, text="", fg="#cc0000")
        add_msg.grid(row=next_row + 1, column=0, columnspan=3, sticky="w")

        def _normalize_ext(s: str) -> str:
            s = (s or "").strip()
            if not s:
                return ""
            if s.startswith("."):
                s = s[1:]
            return "." + s.lower()

        def _add_ext():
            add_msg.config(text="")
            ext = _normalize_ext(add_var.get())
            if not ext:
                add_msg.config(text="Bitte eine Endung eingeben.")
                return
            if not re.match(r"^\.[a-z0-9._+-]+$", ext):
                add_msg.config(text="Nur Buchstaben/Ziffern/._+- erlaubt.")
                return
            if ext in vars_by_ext:
                vars_by_ext[ext].set(True)
                add_var.set("")
                return

            v = tk.BooleanVar(value=True)
            vars_by_ext[ext] = v
            # neue Checkbox hinter die bisherigen
            i = len(vars_by_ext) - 1
            r = 1 + (i // 3)
            c = i % 3
            ttk.Checkbutton(frm, text=ext, variable=v).grid(row=r, column=c, sticky="w", padx=(0, 16))
            add_var.set("")

        ttk.Button(frm, text="Hinzufügen", command=_add_ext).grid(row=next_row, column=2, sticky="w", pady=(10, 0))
        add_entry.bind("<Return>", lambda e: _add_ext())

        # Statusfeld
        status = tk.Text(frm, height=6, width=62, wrap="word")
        status.grid(row=next_row + 2, column=0, columnspan=3, pady=(12, 0), sticky="we")
        status.configure(state="disabled")

        def set_status(msg: str):
            status.configure(state="normal")
            status.delete("1.0", "end")
            status.insert("1.0", msg)
            status.configure(state="disabled")

        # Buttons
        btns_row = next_row + 3
        btns = tk.Frame(frm)
        btns.grid(row=btns_row, column=0, columnspan=3, sticky="e", pady=(12, 0))

        def _persist_ui_state(selected_exts):
            # ui_state speichern (sanft)
            try:
                self.ui_state["file_associations"] = selected_exts
                os.makedirs(os.path.dirname(UI_STATE_FILE), exist_ok=True)
                with open(UI_STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.ui_state, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        def _gather_selected():
            return [k for k, v in vars_by_ext.items() if v.get()]

        def _apply_now():
            exts = _gather_selected()
            if not exts:
                set_status("Keine Endungen ausgewählt.")
                return

            _persist_ui_state(exts)
            utis = self._utis_for_file_association_exts(exts)

            # macOS: duti suchen
            duti_path = None
            try:
                duti_path = self._find_duti_path()
            except Exception:
                duti_path = None

            # Bundle-ID ermitteln
            try:
                bid = self._get_bundle_identifier()
            except Exception:
                bid = "com.maat.notepad"

            if not duti_path:
                # Befehle für den User zusammenstellen und in Clipboard legen
                lines = ["brew install duti"]
                for ext in exts:
                    e = ext.lstrip(".")
                    lines.append(f"duti -s {bid} {e} all")
                for uti, role in utis:
                    lines.append(f"duti -s {bid} {uti} {role}")
                clip = "\n".join(lines)
                try:
                    self.clipboard_clear()
                    self.clipboard_append(clip)
                except Exception:
                    pass
                set_status(
                    "⚠️ `duti` wurde nicht gefunden.\n\n"
                    "1) Öffne Terminal und installiere:\n"
                    "   brew install duti\n"
                    "2) Führe dann diese Befehle aus (bereits in der Zwischenablage):\n\n"
                    + clip
                )
                return

            # duti ist vorhanden → direkt setzen
            ok, errs = [], []
            for ext in exts:
                e = ext.lstrip(".").lower()
                try:
                    proc = subprocess.run([duti_path, "-s", bid, e, "all"], capture_output=True, text=True)
                    if proc.returncode == 0:
                        ok.append(ext)
                    else:
                        errs.append((ext, (proc.stderr or proc.stdout or f"Exit {proc.returncode}").strip()))
                except Exception as ex:
                    errs.append((ext, str(ex)))
            for uti, role in utis:
                label = f"{uti} [{role}]"
                try:
                    proc = subprocess.run([duti_path, "-s", bid, uti, role], capture_output=True, text=True)
                    if proc.returncode == 0:
                        ok.append(label)
                    else:
                        errs.append((label, (proc.stderr or proc.stdout or f"Exit {proc.returncode}").strip()))
                except Exception as ex:
                    errs.append((label, str(ex)))

            msg = []
            if ok:
                msg.append("✅ Verknüpft: " + ", ".join(ok))
            if errs:
                msg.append("\n⚠️ Fehler:")
                for ext, err in errs:
                    msg.append(f"  {ext}: {err}")
            set_status("\n".join(msg) if msg else "Fertig.")

        def _save_only():
            _persist_ui_state(_gather_selected())
            set_status("Auswahl gespeichert. Für systemweite Verknüpfung bitte „Jetzt verlinken“ nutzen.")

        ttk.Button(btns, text="Abbrechen", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Nur speichern", command=_save_only).pack(side="right", padx=6)
        ttk.Button(btns, text="Jetzt verlinken", command=_apply_now).pack(side="right")

        # Shortcuts
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Return>", lambda e: _apply_now())

        # Fokus
        try:
            add_entry.focus_set()
        except Exception:
            pass

    def _install_macos_open_document_handler(self):
        """macOS Finder/Dock: geöffnete Dateien sauber an Tk weiterreichen."""
        try:
            self.createcommand("::tk::mac::OpenDocument", self._on_macos_open_document)
        except Exception:
            pass

    def _on_macos_open_document(self, *paths):
        """Wird von Tk/macOS aufgerufen, wenn Dateien per Finder geöffnet werden."""
        for raw in paths:
            if raw:
                self._pending_external_paths.append(raw)
        self.after_idle(self._drain_pending_external_paths)
        return ""

    def _drain_pending_external_paths(self):
        while self._pending_external_paths:
            path = self._pending_external_paths.pop(0)
            try:
                self.open_external_file(path)
            except Exception as e:
                try:
                    messagebox.showerror("Datei öffnen", f"Konnte Datei nicht öffnen:\n{path}\n\n{e}")
                except Exception:
                    pass

    #Dateiverknüpfung Erstellen
    def open_external_file(self, path):
        if not path:
            return
        existing = self._find_tab_by_external_path(path)
        if existing is not None:
            self._activate_tab(existing)
            return
        try:
            content = self._read_text_file_with_fallback(path)
        except Exception as e:
            messagebox.showerror("Datei öffnen", f"Konnte Datei nicht lesen:\n{path}\n\n{e}")
            return
        self._open_document_in_tab(self._external_to_tab_document(path, content), reuse_blank=True)
        try:
            self.listbox.selection_clear(0, tk.END)
        except Exception:
            pass
        self._update_statusbar()
    
    def _insert_file(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Rust", "*.rs"),
                ("JavaScript", "*.js *.mjs *.cjs"),
                ("Java", "*.java"),
                ("Batch", "*.bat *.cmd"),
                ("PowerShell", "*.ps1"),
                ("Python", "*.py"),
                ("JSON", "*.json"),
                ("YAML", "*.yaml *.yml"),
                ("HTML", "*.html *.htm"),
                ("CSS", "*.css"),
                ("PHP", "*.php"),
                ("LaTeX", "*.tex"),
                ("Shell", "*.sh"),
                ("Command", "*.command"),
                ("Text", "*.txt"),
                ("Markdown", "*.md *.markdown"),
                ("Alle Dateien", "*.*")
            ]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="latin-1") as f:
                    content = f.read()
            except Exception as e:
                messagebox.showerror("Einfügen", f"Kann Datei nicht lesen:\n{e}")
                return
        except Exception as e:
            messagebox.showerror("Einfügen", f"Fehler:\n{e}")
            return

        # An Cursor einfügen
        self.text.insert("insert", content)

        # Bei Skriptdateien Code‑Modus aktivieren (optional)
        if self._is_code_file_path(path) and not self.code_mode.get():
            self.code_mode.set(True)
            self._toggle_code_mode()
        try:
            self._sync_editor_mode_state()
        except Exception:
            pass

        self._update_linenumbers()
        self._schedule_highlight()
#Linter Funktionen
    # ---------------- Tooltip Support ----------------
    def _add_tooltip(self, widget, text: str, *, open_nav_on_click: bool = False, delay_ms: int = 500):
        """
        Hängt an 'widget' einen Hover-Tooltip.
        - text: Tooltip-Text (Mehrzeilig via \n möglich)
        - open_nav_on_click: Klick auf Tooltip öffnet die Navigation
        - delay_ms: Wartezeit bis zur Anzeige
        """
        if not hasattr(self, "_tooltips"):
            self._tooltips = []
        tip = _Tooltip(self, widget, text, delay_ms=delay_ms, open_nav_on_click=open_nav_on_click)
        self._tooltips.append(tip)
        return tip

    def _update_nav_toggle_button(self):
        """Button-Label der Navigation an den aktuellen Zustand anpassen."""
        try:
            if not getattr(self, "nav_toggle_btn", None):
                return
            is_open = self.root_split.sashpos(0) >= 80
            self.nav_toggle_btn.configure(text=("◀" if is_open else "☰"))
        except Exception:
            pass

    def _nav_open(self):
        """Navigation (linke Spalte) aufklappen und Listbox fokussieren."""
        try:
            w = int(self.ui_state.get("root_sash", 280))
            self.root_split.sashpos(0, max(200, w))
        except Exception:
            pass
        self._update_nav_toggle_button()
        try:
            self.listbox.focus_set()
        except Exception:
            pass

    def _nav_close(self):
        """Navigation einklappen."""
        try:
            current = self.root_split.sashpos(0)
            if current >= 80:
                self.ui_state["root_sash"] = int(current)
            self.root_split.sashpos(0, 0)
        except Exception:
            pass
        self._update_nav_toggle_button()

    def _nav_toggle(self):
        """Navigation auf/zu toggeln."""
        try:
            pos = self.root_split.sashpos(0)
            if pos < 50:
                self._nav_open()
            else:
                self._nav_close()
        except Exception:
            self._nav_open()

    def _update_tooltip_theme(self):
        """Tooltip-Farben an Theme anpassen (aufgerufen in _apply_theme)."""
        if not hasattr(self, "_tooltips"):
            return
        c = self._palette()
        for tip in self._tooltips:
            try:
                tip.apply_theme(c)
            except Exception:
                pass


class _Tooltip:
    """Kleiner, eigenständiger Tooltip für Tk-Widgets."""
    def __init__(self, app, widget, text, *, delay_ms=500, open_nav_on_click=False):
        self.app = app
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.open_nav_on_click = open_nav_on_click

        self._after_id = None
        self._win = None
        self._lbl = None

        # Bindings an das Ziel-Widget
        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")  # bei Klick sofort schließen

    def _on_enter(self, _=None):
        self._schedule_show()

    def _on_leave(self, _=None):
        self._cancel_show()
        self._hide()

    def _schedule_show(self):
        self._cancel_show()
        self._after_id = self.app.after(self.delay_ms, self._show)

    def _cancel_show(self):
        if self._after_id:
            try:
                self.app.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._win or not self.widget.winfo_viewable():
            return

        # Position nahe dem Widget
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        except Exception:
            x, y = 100, 100

        # Fenster erzeugen (hier, nicht im __init__)
        self._win = tk.Toplevel(self.app)
        self._win.overrideredirect(True)  # rahmenlos
        try:
            self._win.wm_attributes("-topmost", True)
        except Exception:
            pass

        # Inhalt
        self._lbl = tk.Label(self._win, text=self.text, justify="left", padx=8, pady=6, anchor="w")
        self._lbl.pack(fill="both", expand=True)

        # Klick auf Tooltip: optional Navigation öffnen
        if self.open_nav_on_click:
            self._win.bind("<Button-1>", self._on_click)
            self._lbl.bind("<Button-1>", self._on_click)

        # Theme anwenden
        self.apply_theme(self.app._palette())

        # platzieren
        try:
            self._win.geometry(f"+{x}+{y}")
        except Exception:
            pass

        # Auto-hide, wenn Maus den Tooltip verlässt
        self._win.bind("<Leave>", lambda e: self._hide(), add="+")

    def _hide(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None
            self._lbl = None

    def _on_click(self, _=None):
        self._hide()
        if self.open_nav_on_click:
            try:
                self.app._nav_open()
            except Exception:
                pass

    def apply_theme(self, cdict):
        """Farben aus Palette anwenden."""
        # sanfter Tooltip-Stil
        bg = cdict.get("sunken", cdict.get("panel", "#222222"))
        fg = cdict.get("fg", "#FFFFFF")
        border = cdict.get("border", "#444444")

        if self._win:
            try:
                self._win.configure(bg=border)
            except Exception:
                pass
        if self._lbl:
            try:
                self._lbl.configure(bg=bg, fg=fg)
            except Exception:
                pass

if __name__ == "__main__":
    ensure_storage()
    app = MaatNotepad()

    # Nur für direkten Start im Terminal.
    # In der gebauten .app kommen Finder-Dateien über den macOS-OpenDocument-Handler.
    if len(sys.argv) > 1 and not getattr(sys, "frozen", False):
        args = sys.argv[1:]
        joined = " ".join(args)

        if os.path.exists(joined):
            app.open_external_file(joined)
        else:
            for arg in args:
                if os.path.exists(arg):
                    app.open_external_file(arg)

    app.mainloop()
