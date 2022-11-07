import sys
from PyQt5 import uic
from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem
from yandex_music import Client, ClientAsync
from auth import get_token
import asyncio
import threading
import subprocess
import sqlite3
import collections
# import matplotlib
# from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
# from matplotlib.figure import Figure
# matplotlib.use('Qt5Agg')


class AuthWindow(QMainWindow):
    def __init__(self, mode):
        super().__init__()
        uic.loadUi('ui/auth.ui', self)
        self.setWindowTitle("YMAnalyzer")
        self.authButton.clicked.connect(self.run)
        self.labelError.setVisible(False)
        self.mainWindow = None
        self.mode = mode

    def run(self):
        hwid = str(subprocess.check_output('wmic csproduct get uuid')).split('\\r\\n')[1].strip('\\r').strip()
        connect = sqlite3.connect('mainDB.db')
        cursor = connect.cursor()
        if self.mode == 'start':
            result = cursor.execute("""SELECT id FROM clients WHERE hwid = ?""", (hwid,)).fetchone()
            if result is not None:
                token = cursor.execute("""SELECT token FROM clients WHERE hwid = ?""", (hwid,)).fetchone()[0]
                connect.close()

                self.mainWindow = MainWindow(token)
                self.mainWindow.show()
                self.close()
            else:
                token = get_token()
                if token['result']:
                    accCheck = cursor.execute("SELECT id FROM clients WHERE token = ?",
                                              (token['token'],)).fetchone()
                    if accCheck is not None:
                        cursor.execute("UPDATE clients SET hwid = ? WHERE token = ?", (hwid, token['token']))
                        connect.commit()
                        connect.close()

                        self.mainWindow = MainWindow(token['token'])
                        self.mainWindow.show()
                        self.close()
                    else:
                        userID = Client(token['token']).init().me.account.uid
                        print(userID, hwid, token['token'])
                        cursor.execute("INSERT INTO clients (user_id, hwid, token) VALUES (?, ?, ?)",
                                       (userID, hwid, token['token']))
                        connect.commit()
                        connect.close()

                        self.mainWindow = MainWindow(token['token'])
                        self.mainWindow.show()
                        self.close()
                else:
                    self.labelError.setVisible(True)
        else:
            token = get_token()
            if token['result']:
                cursor.execute("UPDATE clients SET token = ? WHERE hwid = ?", (token['token'], hwid))
                connect.commit()
                connect.close()

                self.mainWindow = MainWindow(token['token'])
                self.mainWindow.show()
                self.close()
            else:
                self.labelError.setVisible(True)


class MainWindow(QMainWindow):
    def __init__(self, token):
        super().__init__()
        uic.loadUi('ui/main.ui', self)
        self.setWindowTitle("YMAnalyzer")
        self.token = token
        self.action.triggered.connect(self.logout)
        self.client = Client(self.token).init()
        self.loginLabel.setText(f'Вы вошли в {self.client.account_status().account.login}.')
        self.trackLabel.setText('Текущая песня в очереди: Нет')
        self.updateButton.clicked.connect(self.updateTableAsync)
        self.igButton.toggled.connect(self.show_graphics)
        self.statButton.toggled.connect(self.show_table)
        self.authWindow = None
        self.main_loop = asyncio.get_event_loop()
        self.thread = threading.Thread(target=self.loop_to_thread, args=(self.main_loop,))
        self.thread.start()

    async def get_track(self):
        def get_label(track):
            try:
                artists = ', '.join(track.artists_name())
                title = track.title
                return f"{artists} - {title}"
            except:
                return 'Нет'

        previous_track = {}
        connect = sqlite3.connect('mainDB.db')
        cursor = connect.cursor()
        client = await ClientAsync(self.token).init()
        while True:
            if not self.isVisible():
                break
            try:
                queues = await client.queues_list()
                last_queue = await client.queue(queues[0].id)
                track_id = last_queue.get_current_track()
                track = await track_id.fetch_track_async()
                if previous_track != track:
                    self.trackLabel.setText(f'Текущая песня в очереди: {get_label(track)}')

                    request = cursor.execute(f"""SELECT id FROM listened_songs
                    WHERE song_id = ?
                    AND user_id IN (SELECT user_id FROM clients WHERE token = ?)""",
                                             (track['id'], self.token)).fetchone()
                    if request is not None:
                        cursor.execute(f"""UPDATE listened_songs
                        SET count = count + 1
                        WHERE song_id = ?
                        AND user_id IN (SELECT user_id FROM clients WHERE token = ?)""", (track['id'], self.token))
                    else:
                        user_id = cursor.execute("SELECT user_id FROM clients WHERE token = ?", (self.token,)).fetchone()[0]
                        cursor.execute("INSERT INTO listened_songs (user_id, song_id, count) VALUES (?, ?, 1)",
                            (user_id, track['id']))
                    connect.commit()
                    previous_track = track
                await asyncio.sleep(10)
            except Exception as e:
                print(e)
        connect.close()

    def logout(self):
        self.authWindow = AuthWindow('relogin')
        self.authWindow.show()
        self.close()

    def loop_to_thread(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.get_track())

    def updateTableAsync(self):
        self.main_loop.create_task(self.updateTable())

    async def updateTable(self):
        async def async_range(count):
            for i in range(count):
                yield i
                await asyncio.sleep(0.0)

        connect = sqlite3.connect('mainDB.db')
        cursor = connect.cursor()
        rows = cursor.execute("""SELECT * FROM listened_songs 
                WHERE user_id IN (SELECT user_id FROM clients WHERE token = ?)""", (self.token,)).fetchall()
        if rows:
            rows = sorted(rows, key=lambda x: x[3], reverse=True)
        self.table.setColumnCount(4)
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(["Название трека", "Исполнители", "Жанр", "Кол-во прослушиваний"])
        self.table.horizontalHeaderItem(0).setToolTip("Название трека")
        self.table.horizontalHeaderItem(1).setToolTip("Исполнители")
        self.table.horizontalHeaderItem(2).setToolTip("Жанр")
        self.table.horizontalHeaderItem(3).setToolTip("Кол-во прослушиваний")
        client = await ClientAsync(self.token).init()
        async for i in async_range(len(rows)):
            song_id = rows[i][2]
            count = rows[i][3]
            track = await client.tracks(song_id)
            artists = ', '.join([artist.name for artist in track[0].artists])
            title = track[0].title
            genre = track[0].albums[0].genre

            self.table.setItem(i, 0, QTableWidgetItem(title))
            self.table.setItem(i, 1, QTableWidgetItem(artists))
            self.table.setItem(i, 2, QTableWidgetItem(genre))
            self.table.setItem(i, 3, QTableWidgetItem(str(count)))
        self.table.resizeColumnsToContents()

    def show_table(self):
        self.label.setVisible(False)
        self.table.setVisible(False)
        self.updateButton.setVisible(False)

    def show_graphics(self):
        self.label.setVisible(True)
        self.table.setVisible(True)
        self.updateButton.setVisible(True)


def except_hook(cls, exception, traceback):
    sys.__excepthook__(cls, exception, traceback)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = AuthWindow('start')
    ex.show()
    sys.excepthook = except_hook
    sys.exit(app.exec_())


#TODO: всякие диаграммы жанров там и т.д и т.п, удалённая бд
