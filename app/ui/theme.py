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
    background-color: transparent;
    border: none;
    border-radius: 0;
}
QFrame#sidebarSeparator {
    color: rgba(255, 255, 255, 24);
    background-color: rgba(255, 255, 255, 24);
    max-height: 1px;
}
QFrame#graphStage {
    background-color: rgba(30, 31, 34, 238);
}
QFrame#playlistStrip {
    background-color: transparent;
    border: none;
}
QFrame#glassPanel {
    background-color: #111416;
    border-color: #2B3232;
}
QFrame#playerBar {
    background-color: #0D1012;
    border-color: rgba(255, 255, 255, 18);
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
QPushButton, QComboBox {
    background-color: rgba(255, 255, 255, 10);
    border: 1px solid rgba(255, 255, 255, 25);
    border-radius: 9px;
    padding: 5px 9px;
    color: #E8E8EB;
}
QPushButton:hover, QComboBox:hover {
    background-color: rgba(255, 255, 255, 20);
    border-color: rgba(255, 255, 255, 54);
}
QPushButton:pressed {
    background-color: rgba(255, 255, 255, 31);
}
QToolButton#railButton, QToolButton#mapCycleButton,
QToolButton#plainActionButton {
    background: transparent;
    border: none;
    padding: 0;
    min-width: 0;
    min-height: 0;
}
QToolButton#railButton:hover, QToolButton#mapCycleButton:hover,
QToolButton#plainActionButton:hover {
    background: rgba(112, 224, 190, 25);
    border: none;
    border-radius: 22px;
}
QToolButton#railButton:pressed, QToolButton#mapCycleButton:pressed,
QToolButton#plainActionButton:pressed {
    background: rgba(112, 224, 190, 42);
    border: none;
    border-radius: 22px;
}
QToolButton::menu-indicator {
    image: none;
    width: 0px;
    height: 0px;
}
QComboBox::drop-down {
    border: none;
    width: 0px;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
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
    background-color: rgba(10, 12, 15, 220);
    border: 1px solid rgba(255, 255, 255, 16);
    border-radius: 11px;
    outline: none;
    padding: 3px;
}
QTableWidget#libraryTable {
    background-color: #111416;
    border-color: #080A0C;
    selection-background-color: #252B2B;
    selection-color: #F2F4F3;
}
QListWidget#queueList {
    background-color: #101315;
    border-color: #080A0C;
    selection-background-color: #252B2B;
    selection-color: #F2F4F3;
}
QTableWidget QHeaderView, QHeaderView,
QTableCornerButton::section {
    background-color: #171A1D;
}
QTableWidget::item, QListWidget::item {
    padding: 5px 7px;
    border-radius: 7px;
}
QTableWidget::item {
    border-top: 1px solid #080A0C;
    border-left: none;
    border-right: none;
    border-bottom: none;
}
QTableWidget::item:hover, QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 8);
}
QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #252B2B;
    color: #F2F4F3;
    outline: none;
    border-left: none;
    border-right: none;
}
QHeaderView::section {
    background-color: #171A1D;
    color: #A9A9B0;
    border: none;
    padding: 7px;
}
QSplitter::handle:horizontal {
    width: 1px;
    background-color: #080A0C;
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
    background: #292F30;
    height: 4px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #B5FBE0,
        stop: .5 #5DD8B7,
        stop: 1 #32877C
    );
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #8BEBCB;
    border: 2px solid #D0FFED;
    width: 11px;
    height: 11px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider#volumeSlider::groove:horizontal {
    height: 3px;
    background: #242A2B;
}
QSlider#volumeSlider::handle:horizontal {
    width: 10px;
    height: 10px;
    margin: -5px 0;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: #0E1113;
    border: none;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #343B3B;
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
