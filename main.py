from tkinter.messagebox import showinfo

import serial
import urllib.request
import websocket
import json
import sys
import datetime

import threading
import time

from tkinter import *


class SerialListener(threading.Thread):

    def __init__(self, s_port):
        super().__init__()
        self.listen = 1
        self.serialPort = s_port
        self.buffer = ""
        self.boardReset = 0

    def run(self):
        while self.listen:
            if self.serialPort.readable():
                dataIn = self.serialPort.readline().decode('utf-8')
                self.buffer += dataIn[:-2]
                if self.buffer.count('DEVICE_STARTUP_BEGIN') == 1:
                    self.boardReset = 1

    def getJSON(self):
        if self.buffer.count('{') == self.buffer.count('}') != 0:
            lastBracket = -1
            for i in range(len(self.buffer)):
                if self.buffer[i] == '}':
                    lastBracket = i
            tempStr = self.buffer[self.buffer.find('{'):lastBracket + 1]
            return 1, tempStr
        if self.buffer.count('{') == 0:
            self.buffer = ''
        return 0, ''

    def flush(self):
        self.buffer = ""


# ------------------------------------------
#                FUNCTION
# ------------------------------------------
def waitForJSONResponse(serialList, timeout=20):
    begin = time.time()
    while not serialList.getJSON()[0]:
        if time.time() - begin > timeout:
            return '{}'
        time.sleep(0.2)

    ret = serialList.getJSON()[1]
    serialList.buffer = ''
    return ret


def wsInAverageValueOnField(field, dataList):
    sum = 0
    for data in dataList:
        tempJSON = json.loads(data)
        if not tempJSON['values'][field] is None and 'values' in tempJSON.keys():
            sum += tempJSON['values'][field]
    return sum / len(dataList)


def getRSSIBar(rssi):
    if rssi >= -67:
        return '░░░░░'
    if rssi >= -70:
        return '░░░░ '
    if rssi >= -80:
        return '░░░  '
    if rssi >= -90:
        return '░░   '
    return '░    '


# ------------------------------------------
#                  MAIN
# ------------------------------------------
if __name__ == '__main__':

    # -----------------------------------------------
    gui = False;
    if len(sys.argv) >= 3 and sys.argv[2] == "gui":
        gui = True

    def alert():
        showinfo('Alerte', 'Bravo !')
    if(gui):
        window = Tk()

        menuBar = Menu(window)

        menuFile = Menu(menuBar, tearoff=0)
        menuFile.add_command(label='New diagnostic', command=alert)
        menuFile.add_command(label='Export .PDF', command=alert)
        menuFile.add_command(label='Export output file')
        menuFile.add_separator()
        menuFile.add_command(label='Exit', command=window.quit)
        menuBar.add_cascade(label='File', menu=menuFile)

        menuDiagnostic = Menu(menuBar, tearoff=0)
        menuDiagnostic.add_command(label='Start diagnostics', command=alert)
        menuDiagnostic.add_command(label='Select Port', command=alert)
        menuBar.add_cascade(label='Diagnostic', menu=menuDiagnostic)

        menuConnectivity = Menu(menuBar, tearoff=0)
        menuConnectivity.add_command(label='Setup WiFi', command=alert)
        menuBar.add_cascade(label='Connectivity', menu=menuConnectivity)

        window.config(menu=menuBar)
        window.title('Diagnostic Tool')
        window.mainloop()
        exit(0)

    # -----------------------------------------------
    portName = 'None'
    connected = 0
    serialListener = None
    serialPort = None

    errorList1Pass = []
    errorList2Pass = []
    errorList3Pass = []
    errorList4Pass = []

    systemData = {}
    wsDataIn = []
    # ------------------------------------------
    # Establishing serial connection

    maxAttempt = 5
    attempt = 0
    if len(sys.argv) >= 2:
        portName = sys.argv[1]
    while not connected:
        try:
            serialPort = serial.Serial(portName, 115200, bytesize=8, parity='N', stopbits=1)
            serialListener = SerialListener(serialPort)

            serialListener.start()
            connected = 1
        except serial.SerialException:
            print('Connection failed : retrying ' + str(attempt) + '/' + str(maxAttempt))
            if attempt >= maxAttempt:
                print('[ERROR] Board could not be reached on ' + portName)
                exit(0)
            attempt += 1
            time.sleep(1)
            connected = 0
    # ------------------------------------------
    # Diagnostic init
    time.sleep(2)
    # ------------------------------------------
    # Wait in case of reset at connexion
    if serialListener.boardReset == 1:
        print('Waiting for device to load...')
        time.sleep(10)
        serialListener.flush()

    cmd = 'diag init\n'
    serialPort.write(cmd.encode('ascii'))

    tempJSON = json.loads(waitForJSONResponse(serialListener))
    dRFID_obj = {'version': (int(tempJSON['device'], 16) & int('FF0000', 16)) >> 16,
                 'state': bool(int(tempJSON['device'], 16) & 1),
                 'autotest': bool((int(tempJSON['device'], 16) & 2) >> 1)}
    dTFT_obj = {'state': bool((int(tempJSON['device'], 16) & 4) >> 2)}
    dBH1750_obj = {'state': bool((int(tempJSON['device'], 16) & 8) >> 3)}
    dBMP280_obj = {'state': bool((int(tempJSON['device'], 16) & 16) >> 4)}

    device_obj = {'device_RFID': dRFID_obj, 'device_TFT': dTFT_obj, 'device_BH1750': dBH1750_obj,
                  'device_BMP280': dBMP280_obj}
    SPIFFS_obj = {'mounted': bool((int(tempJSON['device'], 16) & 32) >> 5)}

    wWifi_obj = {"state": bool((int(tempJSON['device'], 16) & 64) >> 6)}
    wServer_obj = {"state": bool((int(tempJSON['device'], 16) & 128) >> 7)}

    web_obj = {'wifi': wWifi_obj, 'server': wServer_obj}

    auth_obj = {'state': bool((int(tempJSON['device'], 16) & 256) >> 8)}

    systemData['device'] = device_obj
    systemData['SPIFFS'] = SPIFFS_obj
    systemData['web'] = web_obj
    systemData['auth'] = auth_obj
    # ------------------------------------------
    # Diagnostic web
    cmd = 'diag web\n'
    serialPort.write(cmd.encode('ascii'))

    tempJSON = json.loads(waitForJSONResponse(serialListener))
    systemData['web']['wifi']['state'] = bool(tempJSON['web']['wifi']['state'])
    systemData['web']['wifi']['connected'] = bool(tempJSON['web']['wifi']['connected'])
    systemData['web']['wifi']['address'] = tempJSON['web']['wifi']['address']

    systemData['web']['server']['state'] = bool(tempJSON['web']['server']['state'])
    systemData['web']['server']['port'] = tempJSON['web']['server']['port']

    # ------------------------------------------
    # Diagnostic fsfl
    cmd = 'diag fsfl\n'
    serialPort.write(cmd.encode('ascii'))

    tempJSON = json.loads(waitForJSONResponse(serialListener))

    systemData['SPIFFS']['content'] = tempJSON['SPIFFS_list']

    # File wifi_conf.json
    if "wifi_conf.json" in systemData['SPIFFS']['content']:
        cmd = 'diag file=wifi_conf.json\n'
        serialPort.write(cmd.encode('ascii'))

        tempContent = waitForJSONResponse(serialListener)
        tempContent = tempContent[tempContent.find('"content": "') + len('"content": "'):-3]
        tempJSON = json.loads(tempContent)

        systemData['web']['wifi']['SSID'] = tempJSON['ssid']
        systemData['web']['wifi']['password'] = tempJSON['password']
    # ------------------------------------------
    # OUT First Pass
    print('-----------------------------')
    print('SmartCheese diagnostics\n\tDate: ' + str(datetime.datetime.now()))
    print('\tPort: ' + portName)
    print('-------------------------------------------------------------')
    print('First pass : States of devices, SPIFFS, Web and AuthHandler')
    print('-----------------------')
    print('\tDevices:')
    print('\t\tRFID:')
    if systemData['device']['device_RFID']['state']:
        print('\t\t\tState: OK')
    else:
        print('\t\t\tState: ERROR')
        errorList1Pass.append('device.device_RFID.state: ERROR')

    if systemData['device']['device_RFID']['autotest']:
        print('\t\t\tAutotest: OK')
    else:
        print('\t\t\tAutotest: ERROR')
        errorList1Pass.append('device.device_RFID.autotest: ERROR')

    print('\t\t\tVersion: ' + str(systemData['device']['device_RFID']['version']))

    if systemData['device']['device_TFT']['state']:
        print('\t\tTFT: OK')
    else:
        print('\t\tTFT: ERROR')
        errorList1Pass.append('device.device_TFT.state: ERROR')

    if systemData['device']['device_BH1750']['state']:
        print('\t\tBH1750: OK')
    else:
        print('\t\tBH1750: ERROR')
        errorList1Pass.append('device.device_BH1750.state: ERROR')

    if systemData['device']['device_BMP280']['state']:
        print('\t\tBMP280: OK')
    else:
        print('\t\tBMP280: ERROR')
        errorList1Pass.append('device.device_BMP280.state: ERROR')

    print('\tSPIFFS:')
    print('\t\tState: ' + ('OK' if systemData['device']['device_RFID']['state'] else 'ERROR'))
    fileList = ['index.html', 'profiles.json', 'script.js', 'style.css', 'wifi_conf.json']
    fileListPass = 1
    print('\t\tContent: ', end='')
    for file in fileList:
        if not (file in systemData['SPIFFS']['content']):
            fileListPass = 0
            print('\n\t\t\tMissing File: ' + file, end='')
            errorList1Pass.append('SPIFFS.content.file: ' + file + ' MISSING')
    if fileListPass:
        print("OK")

    print('\tWeb:')
    print('\t\tWifi:')
    if systemData['web']['wifi']['state']:
        print('\t\t\tState: OK')
    else:
        print('\t\t\tState: ERROR')
        errorList1Pass.append('web.wifi.state: ERROR')
    print('\t\t\tConnected: ' + ('ONLINE' if systemData['web']['wifi']['connected'] else 'OFFLINE'))
    print('\t\t\tAddress: ' + systemData['web']['wifi']['address'])
    if "wifi_conf.json" in systemData['SPIFFS']['content']:
        print('\t\t\tSSID: ' + systemData['web']['wifi']['SSID'])
        print('\t\t\tPassword: ' + systemData['web']['wifi']['password'])

    print('\t\tServer:')
    if systemData['web']['server']['state']:
        print('\t\t\tState: OK')
    else:
        print('\t\t\tState: ERROR')
        errorList1Pass.append('web.server.state: ERROR')
    print('\t\t\tPort: ' + str(systemData['web']['server']['port']))

    if systemData['auth']['state']:
        print('\t\tAuth: OK')
    else:
        print('\t\tAuth: ERROR')
        errorList1Pass.append('auth.state: ERROR')

    print('-------------------------------------------------------------')
    print('Second pass : Connectivity tests')
    print('-----------------------')
    if not systemData['web']['wifi']['connected'] and systemData['web']['server']['state']:
        print('ABORTED: Board is offline')
        print('#####################################')
        clientIn = str(
            input('[ERROR] The WiFi configuration appears to be incorrect. Would you like to modify it? y / n '))

        if clientIn[0] == 'y':
            goNext = False
            clientInSSID = ''
            clientInPWD = ''

            print('Scanning Networks...')
            cmd = 'diag wifiscan\n'
            serialPort.write(cmd.encode('ascii'))

            tempJSON = json.loads(waitForJSONResponse(serialListener))
            print('Following network accessible on your device :')
            rawNetworks = tempJSON['wifiscan']
            networks = []
            nNet = len(rawNetworks)
            maxSSIDSize = 0
            for i in range(nNet):
                maxIndex = 0
                for k in range(len(rawNetworks)):
                    if rawNetworks[k]['RSSI'] > rawNetworks[maxIndex]['RSSI']:
                        maxIndex = k
                networks.append(rawNetworks[maxIndex])
                if len(rawNetworks[maxIndex]['SSID']) > maxSSIDSize:
                    maxSSIDSize = len(rawNetworks[maxIndex]['SSID'])
                del rawNetworks[maxIndex]

            i = 1
            for net in networks:
                SSIDspace = ' ' * (maxSSIDSize - len(net['SSID']) + (1 if i < 10 else 0))
                print('\t' + str(i) + ': ' + net['SSID'] + SSIDspace + getRSSIBar(net['RSSI']) + ' [' + net[
                    'encryption'] + ']')
                i += 1

            while not goNext:
                goodEntry = False
                clientChoice = 0
                while not goodEntry:
                    clientChoice = int(input('Choose SSID (enter its number): '))
                    if 1 <= clientChoice <= len(networks):
                        goodEntry = True

                clientInSSID = networks[clientChoice - 1]['SSID']
                clientInPWD = str(input('Enter Password (' + clientInSSID + '): '))
                print('New configuration : SSID ->', clientInSSID, ' PWD ->', clientInPWD)
                clientIn = str(input('Is it good? y / n '))
                if clientIn[0] == 'y':
                    goNext = True

            cmd = 'setSSID ' + clientInSSID + '\n'
            serialPort.write(cmd.encode('ascii'))
            time.sleep(0.2)

            cmd = 'setPWD ' + clientInPWD + '\n'
            serialPort.write(cmd.encode('ascii'))
            time.sleep(0.2)

            cmd = 'connect\n'
            serialPort.write(cmd.encode('ascii'))

            print('Waiting for connexion...')
            tempJSON = json.loads(waitForJSONResponse(serialListener))
            if not len(tempJSON.keys()) == 0 and tempJSON['type'] == 'connect' and tempJSON['state'] == 1:
                time.sleep(0.5)

                # UPDATING systemData
                cmd = 'diag web\n'
                serialPort.write(cmd.encode('ascii'))

                tempJSON = json.loads(waitForJSONResponse(serialListener))
                systemData['web']['wifi']['state'] = bool(tempJSON['web']['wifi']['state'])
                systemData['web']['wifi']['connected'] = bool(tempJSON['web']['wifi']['connected'])
                systemData['web']['wifi']['address'] = tempJSON['web']['wifi']['address']

                systemData['web']['server']['state'] = bool(tempJSON['web']['server']['state'])
                systemData['web']['server']['port'] = tempJSON['web']['server']['port']
                print('#####################################')
            else:
                print('Connexion Timeout')
                errorList2Pass.append('WiFi not connected : WARNING')
                errorList3Pass.append('Offline : ABORTED')
                errorList4Pass.append('Offline : ABORTED')

        else:
            errorList2Pass.append('WiFi not connected : WARNING')
            errorList3Pass.append('Offline : ABORTED')
            errorList4Pass.append('Offline : ABORTED')
    if systemData['web']['wifi']['connected'] and systemData['web']['server']['state']:
        print('Trying HTTP connexion on ' + systemData['web']['wifi']['address'] + '...')
        # index.html
        requestHTTPIndex = urllib.request.urlopen("http://" + systemData['web']['wifi']['address']).read().decode(
            'utf-8')
        cmd = 'diag file=index.html\n'
        serialPort.write(cmd.encode('ascii'))

        tempContent = waitForJSONResponse(serialListener)
        tempContent = tempContent[tempContent.find('"content": "') + len('"content": "'):-3]
        if tempContent == requestHTTPIndex.replace('\r\n', ''):
            print('\rFile index.html from HTTP: CONFORM')
        else:
            errorList2Pass.append('file: index.html : NOT CONFORM')
            print('\rFile index.html from HTTP: NOT CONFORM')

        # style.css
        requestHTTPIndex = urllib.request.urlopen(
            "http://" + systemData['web']['wifi']['address'] + "/style.css").read().decode('utf-8')
        cmd = 'diag file=style.css\n'
        serialPort.write(cmd.encode('ascii'))

        tempContent = waitForJSONResponse(serialListener)
        tempContent = tempContent[tempContent.find('"content": "') + len('"content": "'):-3]
        if tempContent == requestHTTPIndex.replace('\r\n', ''):
            print('\rFile style.css from HTTP: CONFORM')
        else:
            errorList2Pass.append('file: style.css : NOT CONFORM')
            print('\rFile style.css from HTTP: NOT CONFORM')

        # script.js
        requestHTTPIndex = urllib.request.urlopen(
            "http://" + systemData['web']['wifi']['address'] + "/script.js").read().decode('utf-8')
        cmd = 'diag file=script.js\n'
        serialPort.write(cmd.encode('ascii'))

        tempContent = waitForJSONResponse(serialListener)
        tempContent = tempContent[tempContent.find('"content": "') + len('"content": "'):-3]
        if tempContent == requestHTTPIndex.replace('\r\n', ''):
            print('\rFile script.js from HTTP: CONFORM')
        else:
            errorList2Pass.append('file: script.js : NOT CONFORM')
            print('\rFile script.js from HTTP: NOT CONFORM')

        print('Trying WebSocket connexion...')
        ws = None
        try:
            ws = websocket.create_connection("ws://" + systemData['web']['wifi']['address'] + "/ws")
            wsDataIn.append(ws.recv())
            print('WebSocket connexion: OK')
        except websocket.WebSocketBadStatusException:
            errorList2Pass.append('WebSocket: ERROR')
            print('WebSocket connexion: 500 - Server Internal ERROR')
        print('-------------------------------------------------------------')
        print('Third pass : WebSocket based data analysis')
        print('-----------------------')
        if ws is None:
            print('ABORTED: WebSocket closed')
            serialListener.listen = 0
            serialListener.join()
            exit(0)
        else:
            dataIndex = 0
            maxDataIndex = 23
            while dataIndex < maxDataIndex + 1:
                spaces = ' ' * (maxDataIndex - dataIndex) * 2
                print('Collecting Data: ' + ('-' * dataIndex) * 2 + spaces + ' | ' + str(
                    int(dataIndex / maxDataIndex * 100)) + '%', end='')
                sys.stdout.flush()
                wsDataIn.append(ws.recv())
                dataIndex += 1
                print('\r', end='')
            print('')
            print('Data analysis (avg. value / 20s):')

            BH1750_range = (10, 600)
            LDR_range = (10, 600)
            BMP280_temp_range = (10, 30)
            BMP280_press_range = (990, 1020)
            MQ9_range = (0.005, 1.5)

            tempLevel = wsInAverageValueOnField('light-level', wsDataIn)
            if BH1750_range[0] < tempLevel < BH1750_range[1]:
                print('\tBH1750: ' + str(tempLevel) + ' lx (seems CORRECT)')
            else:
                errorList3Pass.append('BH1750 seems INCORRECT : WARNING')
                print('\tBH1750: ' + str(tempLevel) + ' lx (seems INCORRECT)')

            tempLevel = wsInAverageValueOnField('ldr-level', wsDataIn)
            if LDR_range[0] < tempLevel < LDR_range[1]:
                print('\tLDR: ' + str(tempLevel) + ' lx (seems CORRECT)')
            else:
                errorList3Pass.append('LDR seems INCORRECT : WARNING')
                print('\tLDR: ' + str(tempLevel) + ' lx (seems INCORRECT)')

            tempLevel = wsInAverageValueOnField('temperature-level', wsDataIn)
            if BMP280_temp_range[0] < tempLevel < BMP280_temp_range[1]:
                print('\tBMP280 / Temp: ' + str(tempLevel) + ' °C (seems CORRECT)')
            else:
                errorList3Pass.append('BMP280 / Temp seems INCORRECT : WARNING')
                print('\tBMP280 / Temp: ' + str(tempLevel) + ' °C (seems INCORRECT)')

            tempLevel = wsInAverageValueOnField('pressure-level', wsDataIn)
            if BMP280_press_range[0] < tempLevel < BMP280_press_range[1]:
                print('\tBMP280 / Press: ' + str(tempLevel) + ' hPa (seems CORRECT)')
            else:
                errorList3Pass.append('BMP280 / Press seems INCORRECT : WARNING')
                print('\tBMP280 / Press: ' + str(tempLevel) + ' hPa (seems INCORRECT)')

            tempLevel = wsInAverageValueOnField('co-level', wsDataIn)
            if MQ9_range[0] < tempLevel < MQ9_range[1]:
                print('\tMQ-9: ' + str(tempLevel) + ' ppm (seems CORRECT)')
            else:
                errorList3Pass.append('MQ-9 seems INCORRECT : WARNING')
                print('\tMQ-9: ' + str(tempLevel) + ' ppm (seems INCORRECT)')

        print('-------------------------------------------------------------')
        print('Fourth pass : WebSocket based output tests')
        print('-----------------------')
        if ws is None:
            print('ABORTED: WebSocket closed')
            serialListener.listen = 0
            serialListener.join()
            exit(0)
        else:
            goNext = False
            while not goNext:
                print('Testing digital outputs:')
                print('\tRelay 1 Test - ', end='')
                ws.send('{"type": "btn-update", "button-number": 1}')
                print('ON - ', end='')
                time.sleep(5)
                ws.send('{"type": "btn-update", "button-number": 1}')
                print('OFF')

                print('\tRelay 2 Test - ', end='')
                ws.send('{"type": "btn-update", "button-number": 2}')
                print('ON - ', end='')
                time.sleep(5)
                ws.send('{"type": "btn-update", "button-number": 2}')
                print('OFF')

                print('Testing analog outputs (0% -> 75%):')
                print('\tPWM 1 Test - ', end='')
                ws.send('{"type": "sliderPWM1-update", "value": 75}')
                print('75% - ', end='')
                time.sleep(5)
                ws.send('{"type": "sliderPWM1-update", "value": 0}')
                print('0%')

                print('\tPWM 2 Test - ', end='')
                ws.send('{"type": "sliderPWM2-update", "value": 75}')
                print('75% - ', end='')
                time.sleep(5)
                ws.send('{"type": "sliderPWM2-update", "value": 0}')
                print('0%')

                if str(input('Retry? y / n '))[0] == 'n':
                    goNext = True

    print('#############################################################')
    print('Summary of the diagnostic')
    print('#######################')

    print("1st Pass : States of devices, SPIFFS, Web and AuthHandler -> ", end='')
    if len(errorList1Pass) == 0:
        print('OK')
    else:
        for temp in errorList1Pass:
            print('\n\t' + temp, end='')
        print('')

    print("2nd Pass : Connectivity tests -> ", end='')
    if len(errorList2Pass) == 0:
        print('OK')
    else:
        for temp in errorList2Pass:
            print('\n\t' + temp, end='')
        print('')

    print("3rd Pass : WebSocket based data analysis -> ", end='')
    if len(errorList3Pass) == 0:
        print('OK')
    else:
        for temp in errorList3Pass:
            print('\n\t' + temp, end='')
        print('')

    print("4th Pass : WebSocket based output tests -> ", end='')
    if len(errorList4Pass) == 0:
        print('seems OK')
    else:
        for temp in errorList4Pass:
            print('\n\t' + temp, end='')
        print('')
    print('#############################################################')
    if serialListener is not None:
        serialListener.listen = 0
        serialPort.write('\n'.encode('ascii'))  # pour forcer la routine readLine à return
        serialListener.join()
    exit(0)
