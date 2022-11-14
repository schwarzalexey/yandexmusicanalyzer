import sys
import subprocess
import sqlite3
from auth import getToken
from PyQt6 import uic, QtCore
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtCharts import QChart, QChartView, QPieSeries
from yandex_music import Client, Track


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
                token = getToken()
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
            token = getToken()
            if token['result']:
                cursor.execute("UPDATE clients SET token = ? WHERE hwid = ?", (token['token'], hwid))
                connect.commit()
                connect.close()

                self.mainWindow = MainWindow(token['token'])
                self.mainWindow.show()
                self.close()
            else:
                self.labelError.setVisible(True)


class WorkerChart(QObject):
    genreListSignal = pyqtSignal(list)
    artistListSignal = pyqtSignal(list)
    finishedSignal = pyqtSignal()

    def __init__(self, token):
        super().__init__()
        self.token = token
        self.client = Client(self.token).init()
        self.running = False

    def runThread(self):
        def genreChartData():
            connect = sqlite3.connect('mainDB.db')
            cursor = connect.cursor()
            request = cursor.execute("""SELECT song_id, count FROM listened_songs
                        WHERE user_id IN (SELECT user_id FROM clients WHERE token = ?)""",
                                     (self.token,)).fetchall()
            connect.close()
            if not request:
                return
            trackIds = [track[0] for track in request]
            tracks = self.client.tracks(trackIds)
            genres = [(tracks[i].albums[0].genre, request[i][1]) for i in range(len(tracks))]
            genresDict = {}
            for genre in genres:
                if genre[0] in genresDict.keys():
                    genresDict[genre[0]] += int(genre[1])
                else:
                    genresDict.update({genre[0]: int(genre[1])})
            genresList = list(sorted(genresDict.items(), key=lambda item: item[1], reverse=True))
            return genresList

        def artistChartData():
            connect = sqlite3.connect('mainDB.db')
            cursor = connect.cursor()
            request = cursor.execute("""SELECT song_id, count FROM listened_songs
                        WHERE user_id IN (SELECT user_id FROM clients WHERE token = ?)""",
                                     (self.token,)).fetchall()
            connect.close()
            if not request:
                return
            trackIds = [track[0] for track in request]
            tracks = self.client.tracks(trackIds)
            artistsAndCountList = [(tracks[i].artists, request[i][1]) for i in range(len(tracks))]
            artistsDict = {}
            for artists, count in artistsAndCountList:
                if len(artists) != 1:
                    for artist in artists:
                        if artist.name in artistsDict.keys():
                            artistsDict[artist.name] += int(count)
                        else:
                            artistsDict.update({artist.name: int(count)})
                else:
                    artist = artists[0]
                    if artist.name in artistsDict.keys():
                        artistsDict[artist.name] += int(count)
                    else:
                        artistsDict.update({artist.name: int(count)})
            overallSum = sum(artistsDict.values())
            otherSum = 0
            temporaryList = list(sorted(artistsDict.items(), key=lambda item: item[1]))
            for i in range(len(temporaryList)):           
                if int(temporaryList[i][1]) / overallSum < 0.05:
                    temporaryList[i] += (False,)
                    otherSum += int(pair[1])
                else:
                    temporaryList[i] += (True,)
            temporaryList.append(("Other artists", otherSum, True))
            artistsDict = {} # name: count for name, count, flag in temporaryList if flag
            for dataTuple in temporaryList:
                if not dataTuple[2]:
                    continue
                artistsDict.update({dataTuple[0]: dataTuple[1]})
            del temporaryList
            artistsList = list(sorted(artistsDict.items(), key=lambda item: item[1], reverse=True))
            return artistsList

        self.running = True
        while self.running:
            genresChartSeries = genreChartData()
            self.genreListSignal.emit(genresChartSeries)
            artistChartSeries = artistChartData()
            self.artistListSignal.emit(artistChartSeries)
            QtCore.QThread.msleep(30000)
        self.connect.close()
        self.finishedSignal.emit()


class WorkerTable(QObject):
    listSignal = pyqtSignal(list)
    finishedSignal = pyqtSignal()

    def __init__(self, token):
        super().__init__()
        self.token = token
        self.client = Client(self.token).init()

    def runThread(self):
        connect = sqlite3.connect('mainDB.db')
        cursor = connect.cursor()
        rows = cursor.execute("""SELECT * FROM listened_songs
                        WHERE user_id IN (SELECT user_id FROM clients WHERE token = ?)""", (self.token,)).fetchall()
        connect.close()
        if rows:
            rows = sorted(rows, key=lambda x: x[3], reverse=True)
        tracks = [(self.client.tracks(row[2]), row[3]) for row in rows]

        self.listSignal.emit(tracks)
        self.finishedSignal.emit()


class WorkerTrack(QObject):
    listSignal = pyqtSignal(Track)
    finishedSignal = pyqtSignal()

    def __init__(self, token, parent):
        super().__init__()
        self.token = token
        self.parent = parent
        self.client = Client(self.token).init()

    def runThread(self):
        previousTrack = {}
        connect = sqlite3.connect('mainDB.db')
        cursor = connect.cursor()
        client = Client(self.token).init()
        while True:
            if not self.parent.isVisible():
                break
            try:
                queues = client.queuesList()
                lastQueue = client.queue(queues[0].id)
                trackId = lastQueue.getCurrentTrack()
                track = trackId.fetchTrack()
                if previousTrack != track:
                    self.listSignal.emit(track)
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
                        userId = cursor.execute("SELECT user_id FROM clients WHERE token = ?",
                                                (self.token,)).fetchone()[0]
                        cursor.execute("INSERT INTO listened_songs (user_id, song_id, count) VALUES (?, ?, 1)",
                                       (userId, track['id']))
                    connect.commit()
                    previousTrack = track
            except Exception as e:
                print(e)
            QtCore.QThread.msleep(10000)
        connect.close()
        self.finishedSignal.emit()


class MainWindow(QMainWindow):
    def __init__(self, token):
        super().__init__()
        uic.loadUi('ui/main.ui', self)
        self.setWindowTitle("YMAnalyzer")
        self.token = token
        self.action.triggered.connect(self.logout)
        self.client = Client(self.token).init()
        self.loginLabel.setText(f'Вы вошли в аккаунт {self.client.account_status().account.login}.')
        self.trackLabel.setText('Текущая песня в очереди: Нет')
        self.updateButton.clicked.connect(self.startUpdateTableThread)
        self.igButton.toggled.connect(self.show_graphics)
        self.statButton.toggled.connect(self.show_table)
        self.genreChartWidget.setVisible(False)
        self.artistChartWidget.setVisible(False)
        self.authWindow = None
        self.chartView = None
        self.layout = None
        # --------------------------- Chart updater
        self.objThread = QThread()
        self.workerChart = WorkerChart(self.token)
        self.workerChart.moveToThread(self.objThread)
        self.workerChart.finishedSignal.connect(self.objThread.exit)
        self.workerChart.genreListSignal.connect(self.onGenrePieChartUpdate)
        self.workerChart.artistListSignal.connect(self.onArtistPieChartUpdate)
        self.objThread.started.connect(self.workerChart.runThread)
        self.objThread.start()
        # --------------------------- Track updater
        self.objThreadTrack = QThread()
        self.workerTrack = WorkerTrack(self.token, self)
        self.workerTrack.moveToThread(self.objThreadTrack)
        self.workerTrack.finishedSignal.connect(self.objThreadTrack.exit)
        self.workerTrack.listSignal.connect(self.onTrackUpdate)
        self.objThreadTrack.started.connect(self.workerTrack.runThread)
        self.objThreadTrack.start()
        # --------------------------- Initialize space for WorkerTable
        self.objThreadTable = None
        self.workerTable = None

    def onTrackUpdate(self, track):
        def getLabel(track_):
            try:
                artists = ', '.join(track_.artists_name())
                title = track_.title
                return f"{artists} - {title}"
            except Exception as e:
                print(e)
                return 'Нет'

        self.trackLabel.setText(f'Текущая песня в очереди: {getLabel(track)}')

    def logout(self):
        self.authWindow = AuthWindow('relogin')
        self.authWindow.show()
        self.close()

    def startUpdateTableThread(self):
        self.objThreadTable = QThread()
        self.workerTable = WorkerTable(self.token)
        self.workerTable.moveToThread(self.objThreadTable)
        self.workerTable.finishedSignal.connect(self.objThreadTable.exit)
        self.workerTable.listSignal.connect(self.onTableUpdate)
        self.objThreadTable.started.connect(self.workerTable.runThread)
        self.objThreadTable.start()

    def onTableUpdate(self, data):
        self.table.setColumnCount(4)
        self.table.setRowCount(len(data))
        self.table.setHorizontalHeaderLabels(["Название трека", "Исполнители", "Жанр", "Кол-во прослушиваний"])
        self.table.horizontalHeaderItem(0).setToolTip("Название трека")
        self.table.horizontalHeaderItem(1).setToolTip("Исполнители")
        self.table.horizontalHeaderItem(2).setToolTip("Жанр")
        self.table.horizontalHeaderItem(3).setToolTip("Кол-во прослушиваний")
        for i, dataTuple in enumerate(data):
            count = dataTuple[1]
            artists = ', '.join([artist.name for artist in dataTuple[0][0].artists])
            title = dataTuple[0][0].title
            genre = dataTuple[0][0].albums[0].genre

            self.table.setItem(i, 0, QTableWidgetItem(title))
            self.table.setItem(i, 1, QTableWidgetItem(artists))
            self.table.setItem(i, 2, QTableWidgetItem(genre))
            self.table.setItem(i, 3, QTableWidgetItem(str(count)))
        self.table.resizeColumnsToContents()

    def onGenrePieChartUpdate(self, data):
        series = QPieSeries()
        for genre in data:
            series.append(genre[0], genre[1])
        chart = QChart()
        chart.addSeries(series)
        chart.createDefaultAxes()
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setTitle("Наиболее любимые жанры")
        chart.legend().setInteractive(True)
        self.chartView = QChartView(chart)
        self.layout = QHBoxLayout(self.genreChartWidget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.chartView)

    def onArtistPieChartUpdate(self, data):
        series = QPieSeries()
        for genre in data:
            series.append(genre[0], genre[1])
        chart = QChart()
        chart.addSeries(series)
        chart.createDefaultAxes()
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setTitle("Наиболее любимые артисты")
        chart.legend().setInteractive(True)
        self.chartView = QChartView(chart)
        self.layout = QHBoxLayout(self.artistChartWidget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.chartView)

    def show_table(self):
        self.label.setVisible(False)
        self.table.setVisible(False)
        self.updateButton.setVisible(False)
        # ---------------------------
        self.genreChartWidget.setVisible(True)
        self.artistChartWidget.setVisible(True)

    def show_graphics(self):
        self.label.setVisible(True)
        self.table.setVisible(True)
        self.updateButton.setVisible(True)
        # ---------------------------
        self.genreChartWidget.setVisible(False)
        self.artistChartWidget.setVisible(False)


def except_hook(cls, exception, traceback):
    sys.__excepthook__(cls, exception, traceback)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = AuthWindow('start')
    ex.show()
    sys.excepthook = except_hook
    sys.exit(app.exec())
