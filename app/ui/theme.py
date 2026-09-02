from __future__ import annotations


# A deliberately neutral "smoked glass" system: it stays legible on Windows
# without borrowing Spotify's green or the usual blue desktop-app accents.
DARK_THEME = """
* {
    font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
    color: #ECECEE;
}
QMainWindow, QWidget#appRoot {
    background-color: #07090B;
}
QWidget#contentOverlay, QWidget#mapLayer, QSplitter {
    background: transparent;
}
QFrame#glassPanel, QFrame#playerBar, QFrame#topBar,
QFrame#playlistStrip, QFrame#graphStage {
    background-color: rgba(27, 29, 33, 166);
    border: 1px solid rgba(255, 255, 255, 25);
    border-radius: 15px;
}
QFrame#sidebar {
    background-color: rgba(15, 17, 20, 172);
    border: 1px solid rgba(255, 255, 255, 22);
    border-radius: 14px;
}
QFrame#sidebarSeparator {
    color: rgba(255, 255, 255, 24);
    background-color: rgba(255, 255, 255, 24);
    max-height: 1px;
}
QFrame#graphStage {
    background-color: rgba(30, 31, 34, 238);
}
QFrame#playerBar {
    background-color: #24262A;
}
QLabel#appTitle {
    font-size: 18px;
    font-weight: 650;
    color: #F7F7F8;
}
QLabel#sectionCaption {
    color: #AFAFB5;
    font-size: 11px;
    font-weight: 650;
}
QLabel#appSubtitle, QLabel#playerArtist, QLabel#playlistCardName {
    color: #A3A3AA;
}
QLabel#playerTitle {
    color: #F4F4F5;
    font-weight: 650;
}
QLabel#trackCellTitle, QLabel#nextTrackTitle {
    color: #EEEEF0;
    font-weight: 600;
}
QLabel#trackCellArtist, QLabel#nextTrackArtist, QLabel#nextTrackCaption {
    color: #96969E;
    font-size: 10px;
}
QPushButton, QToolButton, QComboBox {
    background-color: rgba(255, 255, 255, 10);
    border: 1px solid rgba(255, 255, 255, 25);
    border-radius: 9px;
    padding: 5px 9px;
    color: #E8E8EB;
}
QPushButton:hover, QToolButton:hover, QComboBox:hover {
    background-color: rgba(255, 255, 255, 20);
    border-color: rgba(255, 255, 255, 54);
}
QPushButton:pressed, QToolButton:pressed {
    background-color: rgba(255, 255, 255, 31);
}
QToolButton#mapCycleButton {
    min-width: 82px;
}
QPushButton:disabled {
    color: #74747B;
    background-color: rgba(255, 255, 255, 5);
}
QComboBox QAbstractItemView {
    background-color: #26262A;
    border: 1px solid rgba(255, 255, 255, 38);
    selection-background-color: rgba(255, 255, 255, 24);
}
QTableWidget, QListWidget {
    background-color: rgba(10, 12, 15, 148);
    border: 1px solid rgba(255, 255, 255, 16);
    border-radius: 11px;
    outline: none;
    padding: 3px;
}
QTableWidget QHeaderView, QHeaderView,
QTableCornerButton::section {
    background-color: #26262A;
}
QTableWidget::item, QListWidget::item {
    padding: 6px;
    border-radius: 7px;
}
QTableWidget::item:hover, QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 8);
}
QTableWidget::item:selected, QListWidget::item:selected {
    background-color: rgba(255, 255, 255, 20);
}
QHeaderView::section {
    background-color: #26262A;
    color: #A9A9B0;
    border: none;
    padding: 7px;
}
QTabWidget::pane {
    border: 1px solid rgba(255, 255, 255, 25);
    border-radius: 11px;
    background-color: rgba(31, 31, 35, 214);
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #9999A1;
    padding: 8px 12px;
}
QTabBar::tab:selected {
    color: #F4F4F5;
    border-bottom: 2px solid #D6D6DA;
}
QSlider::groove:horizontal {
    background: rgba(255, 255, 255, 48);
    height: 3px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #D8D8DC;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #F1F1F3;
    width: 9px;
    height: 9px;
    margin: -4px 0;
    border-radius: 5px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: #202024;
    border: none;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #5B5B62;
    border-radius: 4px;
    min-height: 22px;
    min-width: 22px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0px;
    height: 0px;
}
QFrame#playlistCard {
    background-color: rgba(255, 255, 255, 7);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 12px;
}
QFrame#playlistCard:hover {
    background-color: rgba(255, 255, 255, 16);
    border-color: rgba(255, 255, 255, 47);
}
QFrame#playlistCard[selected="true"] {
    background-color: rgba(255, 255, 255, 22);
    border-color: rgba(255, 255, 255, 68);
}
QFrame#playlistCard[moodCard="true"] {
    background-color: rgba(255, 255, 255, 11);
}
QMenu {
    background-color: #29292D;
    border: 1px solid rgba(255, 255, 255, 42);
    border-radius: 10px;
    padding: 5px;
}
QMenu::item {
    padding: 7px 24px 7px 11px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: rgba(255, 255, 255, 17);
}
QStatusBar {
    background-color: #07090B;
    color: #92929A;
}
"""
