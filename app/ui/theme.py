from __future__ import annotations


# A deliberately neutral "smoked glass" system: it stays legible on Windows
# without borrowing Spotify's green or the usual blue desktop-app accents.
DARK_THEME = """
* {
    font-family: "Segoe UI", Arial, sans-serif;
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
    background-color: transparent;
    border: none;
    border-radius: 0;
}
QFrame#libraryPanel, QFrame#queuePanel {
    background: #111416;
    border: none;
    border-radius: 15px;
}
QFrame#libraryPanel[liquidGlass="true"], QFrame#queuePanel[liquidGlass="true"] {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(17, 20, 22, 0),
        stop: .28 rgba(17, 20, 22, 88),
        stop: .5 rgba(17, 20, 22, 236),
        stop: .56 rgba(17, 20, 22, 255),
        stop: 1 rgba(17, 20, 22, 255)
    );
    border: none;
    border-radius: 15px;
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
QLabel#playlistSectionTitle {
    color: #E2E8E5;
    font-size: 12px;
    font-weight: 700;
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
    font-size: 13px;
    font-weight: 600;
}
QLabel#trackCellArtist, QLabel#nextTrackArtist, QLabel#nextTrackCaption {
    color: #96969E;
    font-size: 12px;
}
QTableWidget#libraryTable {
    font-size: 12px;
}
QWidget#trackRowCell[rowState="hover"] {
    background-color: rgba(255, 255, 255, 18);
}
QWidget#trackRowCell[rowState="selected"] {
    background-color: #303334;
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
QToolButton#railButton, QToolButton#mapCycleButton {
    background: transparent;
    border: none;
    /* QToolButton aligns the large glyph by its font line box; a little
       bottom padding lifts the visible arrow to the optical center. */
    padding: 0 0 5px 0;
}
QToolButton#plainActionButton {
    background: transparent;
    border: none;
    padding: 0;
    min-width: 0;
    min-height: 0;
}
QToolButton#plainActionButton:hover {
    background: rgba(112, 224, 190, 25);
    border: none;
    border-radius: 22px;
}
QToolButton#plainActionButton:pressed {
    background: rgba(112, 224, 190, 42);
    border: none;
    border-radius: 22px;
}
QToolButton#playlistScrollButton {
    background: rgba(36, 53, 55, 205);
    border: 1px solid rgba(181, 251, 224, 72);
    border-radius: 13px;
    color: #B5FBE0;
    font-size: 30px;
    font-weight: 600;
    padding: 0;
}
QToolButton#playlistScrollButton:hover {
    background: rgba(82, 150, 132, 218);
    border-color: rgba(181, 251, 224, 128);
    color: #F1FFF8;
}
QToolButton#playlistScrollButton:pressed {
    background: rgba(112, 197, 171, 230);
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
    background: transparent;
    border: none;
    border-radius: 0;
    selection-background-color: #303334;
    selection-color: #F2F4F3;
}
QListWidget#queueList {
    background: transparent;
    border: none;
    border-radius: 0;
    selection-background-color: #252B2B;
    selection-color: #F2F4F3;
}
QTableWidget QHeaderView, QHeaderView,
QTableCornerButton::section {
    background: transparent;
}
QTableWidget#libraryTable QHeaderView::section {
    background: transparent;
}
QTableWidget::item, QListWidget::item {
    padding: 5px 7px;
    border-radius: 0;
}
QTableWidget::item {
    border-top: 1px solid #080A0C;
    border-left: none;
    border-right: none;
    border-bottom: none;
}
QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 8);
}
QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #303334;
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
QHeaderView::section:first {
    padding: 7px 5px 7px 9px;
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
QScrollBar:vertical {
    background: transparent;
    border: none;
    width: 12px;
    margin: 5px 2px;
}
QScrollBar:horizontal {
    background: transparent;
    border: none;
    height: 12px;
    margin: 2px 5px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(116, 148, 143, 180),
        stop: .5 rgba(151, 205, 188, 220),
        stop: 1 rgba(92, 133, 126, 180)
    );
    border: none;
    border-radius: 6px;
    min-height: 44px;
    min-width: 44px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(140, 190, 177, 210),
        stop: .5 rgba(188, 240, 220, 235),
        stop: 1 rgba(111, 165, 153, 210)
    );
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    height: 0px;
}
QTableWidget#libraryTable QScrollBar:vertical {
    background: transparent;
    width: 14px;
    margin: 8px 1px 8px 0;
}
QTableWidget#libraryTable QScrollBar::handle:vertical {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(93, 151, 137, 160),
        stop: .5 rgba(139, 235, 203, 205),
        stop: 1 rgba(69, 119, 110, 160)
    );
    border: none;
    min-height: 44px;
    border-radius: 7px;
}
QTableWidget#libraryTable QScrollBar::handle:vertical:hover {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(115, 188, 169, 190),
        stop: .5 rgba(176, 247, 220, 225),
        stop: 1 rgba(84, 150, 135, 190)
    );
}
QTableWidget#libraryTable QScrollBar::add-page:vertical,
QTableWidget#libraryTable QScrollBar::sub-page:vertical {
    background: transparent;
}
QFrame#playlistCard {
    background: transparent;
    border: none;
    border-radius: 12px;
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
