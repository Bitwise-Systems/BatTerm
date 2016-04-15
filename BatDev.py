#!/usr/bin/env python
#
#   BatDev.py -- Serial monitor for BatDevT.ino communication
#
#       Version 1:  Forked from Simple.py, version 6.
#                   Add support for "local" printing of help text.
#
#       Version 2:  Added battery capacity command insertion
#
#       Version 3:  Support for script loading ('compile' command)
#
#       Version 4:  General escape-sequence mechanism in inbound stream
#
#       Usage:      BatDev.py [-a] [-x] [-b <baudrate>]
#
#

import sys, os, serial, threading, glob, time, select, getopt, readline
from datetime import datetime

helpFile = os.environ['HOME'] + '/MSR/BatDevHelp.txt'            # Path to 'help' text
scriptFolder = os.environ['HOME'] + '/MSR/BatDevScripts/'        # Path to script folder
inventoryFile = os.environ['HOME'] + '/MSR/BatDevInventory.py'   # Path to battery inventory

execfile(inventoryFile)        # Define battery inventory

running = threading.Event()    # Allows the reader thread to shut...
                               # ...down the writer, and vice versa.

class Terminal:
    def __init__(self, port, baudrate):
        self.serial = serial.serial_for_url(port, baudrate, timeout=0)


    def start(self):
        self.serial.flushInput()    # Requires Arduino sketch to 'delay(600)' in setup()
        running.set()               # Both threads will shut down when 'running' is cleared

      # start serial-->console thread
        self.receiver_thread = threading.Thread(target=self.reader)
        self.receiver_thread.setDaemon(1)
        self.receiver_thread.start()

      # start console-->serial thread
        self.transmitter_thread = threading.Thread(target=self.writer)
        self.transmitter_thread.setDaemon(1)
        self.transmitter_thread.start()


    def join(self):
        self.receiver_thread.join()
        self.transmitter_thread.join()

#---------------------------------- Reader ----------------------------------

    def translate(self, s):
        c = 16 * int(s[0], 16) + int(s[1], 16)
        if c == 0x00:
            return '\xc2\xb7'
        elif c < 0x20 or c > 0x7e:
            return '.'
        else:
            return chr(c)


    def hexDump(self):
        for addr in range(0x100, 0x900, 0x10):
            line = ''
            c = ''
#           c = self.serial.read(1)
            while c != '\n':
                line += c
                c = self.serial.read(1)
            sys.stdout.write('%04X:  ' % addr)
            sys.stdout.write('%s  ' % line[0:24])
            sys.stdout.write('%s  ' % line[24:])
            for h in line.split():
                sys.stdout.write('%s' % self.translate(h))
            sys.stdout.write('\n')
            sys.stdout.flush()


    def reader(self):    # Thread for serial port --> console
        try:
            while running.isSet():
                char = self.serial.read(1)      # timeout = 0 implies a
                if char == '':                  # ...non-blocking read. Just
                    continue                    # ...spin until something arrives.

                if char != '$':                 # Pass non-escape sequences to host.
                    sys.stdout.write(char)
                    sys.stdout.flush()
                else:
                    char = self.serial.read(1)  # Otherwise pick up escape code

                    if char == 'Q' and autoExit == True:   # Quit if escape-code
                        running.clear()                    # termination is active

                    elif char == 'D':           # SRAM dump follows
                        self.hexDump()

                    else:                       # All others are just themselves
                        sys.stdout.write(char)
                        sys.stdout.flush()


        except serial.SerialException, e:
            running.clear()
            raise

#---------------------------------- Writer ----------------------------------

    def printHelp(self):
        try:
            for line in open(helpFile):
                sys.stderr.write(line)
                sys.stderr.flush()

        except IOError:
            sys.stderr.write("Sorry, can't find help file\n")
            sys.stderr.flush()


    def insertCapacity(self, line):
        try:
            (cmd, arg) = line.split()
            if cmd == 'b':
                try:
                    self.serial.write('bc %s\n' % inventory[arg]['mAh'])
                    self.serial.flush()
                except KeyError:
                    pass

        except ValueError:
            pass


    def include(self, filename):
        try:
            for line in open(scriptFolder + filename):
                (cmd, file) = self.tokenize(line)
                if cmd[0:1] == '#':
                    continue
                if cmd == 'include':
                    self.include(file)
                else:
                    self.serial.write(line)
                    self.serial.flush()
                    time.sleep(0.050)        # poor man's flow-control

        except IOError:
            sys.stderr.write("Sorry, can't find '%s'\n" % filename)
            sys.stderr.flush()


    def insertScript(self, filename):
        self.serial.write('comp\n')
        self.serial.flush()
        self.include(filename)
        self.serial.write('\n\n')
        self.serial.flush()


    def tokenize(self, line):                  # Isolate first two words in a line
        tok = line.split(None, 2) + ['','']
        return (tok[0], tok[1])


    def writer(self):    # Thread for console --> serial port
        try:
            while running.isSet():
                if sys.stdin in select.select([sys.stdin],[],[],0)[0]:  # non-blocking read
                    line = sys.stdin.readline()
                    (cmd, file) = self.tokenize(line)
                    if cmd == 'help':
                        self.printHelp()
                    elif cmd == 'compile':
                        self.insertScript(file)
                    elif cmd == 'quit':
                        running.clear()
                    else:
                        self.serial.write(line)
                        self.serial.flush()
                        if cmd == 'b':
                            self.insertCapacity(line)
                        time.sleep(flowDelay)
        except:
            running.clear()
            raise

#---------------------------------- Mainline ----------------------------------

def abort(message):
        sys.stderr.write(message + '\n')
        sys.exit(1)


def main():
    print "Run date: %s" % datetime.now().strftime('%b %d %Y, %H:%M:%S')
    try: (options, residue) = getopt.getopt(sys.argv[1:], 'axb:')
    except getopt.GetoptError, errorMessage:
        abort(str(errorMessage))

    baudrate = 38400
    global autoExit
    autoExit = False
    alert = False
    for (opt, val) in options:
        if opt == '-a':
            alert = True
        elif opt == '-x':
            autoExit = True
        elif opt == '-b':
            try: baudrate = int(val)
            except ValueError:
                abort("Invalid baudrate")
            if baudrate not in [300, 1200, 4800, 9600, 14400, 19200, 28800, 38400, 57600, 115200]:
                abort("Unsupported baudrate")

    global flowDelay
    flowDelay = 0
    portList = glob.glob('/dev/cu.usb*')
    devices = ['/dev/ttys000', '/dev/ttys001', '/dev/ttys002', '/dev/ttys003']
    try:
        i = devices.index(os.ttyname(0))    # throws exception if stdin is not a TTY
    except OSError:
        i = 0
        flowDelay = 0.100    # prevent overrun when input is not coming from human hands
    try:
        port = portList[i]
    except IndexError:
        abort("No USB port found")

    try:
        term = Terminal(port, baudrate)
        time.sleep(1.5)                    # Wait out the Arduino boot loader

    except serial.SerialException, e:
        abort("Could not open port %r: %s" % (port, e))

    term.start()
    term.join()        # Twiddle thumbs until reader & writer threads both exit

    sys.stderr.write("Exiting monitor...\n")
    if alert == True:
        for n in range(0, 3):
            os.system('afplay /System/Library/Sounds/Glass.aiff')


if __name__ == '__main__':
    main()
