#!/usr/bin/env python3

import os, sys
from enum import Enum, auto

import tcf
from tcf import protocol
from tcf.util import sync

import asyncio

def lookahead(iterable):
    it = iter(iterable)
    last = next(it)
    for val in it:
        yield last, False
        last = val
    yield last, True

class AHBUART(Enum):
    ST_CMD = auto()
    ST_ADDR0 = auto()
    ST_ADDR1 = auto()
    ST_ADDR2 = auto()
    ST_ADDR3 = auto()
    ST_DATA0 = auto()
    ST_DATA1 = auto()
    ST_DATA2 = auto()
    ST_DATA3 = auto()

class AHBJTAG:
    def __init__(self, irlen = 6, ainst = 0x2, dinst = 0x3):
        HW_URL = os.getenv("HW_SERVER_URL", "TCP:localhost:3121")
        print(f"HW_URL = {HW_URL}")
        self.ainst = ainst.to_bytes(1)
        self.dinst = dinst.to_bytes(1)
        self.irlen = irlen
        protocol.startEventQueue()
        c = tcf.connect(HW_URL)
        self.cmd = sync.CommandControl(c)
        self.cable = self.cmd.Jtag.getChildren("").getE()[0]

        self.reset()

    def reset(self):
        r = self.cmd.Jtag.sequence(self.cable, dict(), [["state", "RESET", 5]], b"").getE()

    def read(self, address, length):
        kw = {"byteorder": "little"}
        commands = [
            ["shift", "i", False, self.irlen, {"state": "IDLE"}],
            ["shift", "d", False,         35, {"state": "IDLE"}],
            ["shift", "i", False, self.irlen, {"state": "IDLE"}]
        ] + [
            ["shift", "d", True,          33, {"state":"IDLE"}] for _ in range(length)
        ]
        content = [
            self.ainst,
            address.to_bytes(4, **kw) + b"\x02",
            self.dinst] + [b"\x00\x00\x00\x00\x00" if last else b"\x00\x00\x00\x00\x01" for _, last in lookahead(range(length))]


        r = self.cmd.Jtag.sequence(self.cable, dict(), commands, b"".join(content)).getE()
        assert len(r) == 5*length
        assert r[4::5] == length * b"\x01"
        return [int.from_bytes(r[i:][:4], **kw) for i in range(0, 5*length, 5)]

    def write(self, address, datav):
        kw = {"byteorder": "little"}
        commands = [
            ["shift", "i", False, self.irlen, {"state": "IDLE"}],
            ["shift", "d", False,         35, {"state": "IDLE"}],
            ["shift", "i", False, self.irlen, {"state": "IDLE"}]
        ] + [
            ["shift", "d", True,          33, {"state":"IDLE"}] for _ in datav
        ]
        content = [
            self.ainst,
            address.to_bytes(4, **kw) + b"\x06",
            self.dinst] + [d.to_bytes(4, **kw) + b"\x00" if last else d.to_bytes(4, **kw) + b"\x01" for d, last in lookahead(datav)]


        r = self.cmd.Jtag.sequence(self.cable, dict(), commands, b"".join(content)).getE()
        assert len(r) == 5*len(datav)

class AHBUARTParser:
    def __init__(self, read_cb, write_cb):
        self.state = AHBUART.ST_CMD
        self.write_not_read = True
        self.length = 0
        self.address = 0
        self.data = 0
        self.datav = []
        self.read_cb = read_cb
        self.write_cb = write_cb

    def step(self, e):
        match self.state:
            case AHBUART.ST_CMD:
                if (e & 0x80) == 0x80:
                    self.write_not_read = ((e & 0x40) == 0x40)
                    self.length = (e & 0x3f) + 1
                    self.state = AHBUART.ST_ADDR0
            case AHBUART.ST_ADDR0:
                self.address = e << 24
                self.state = AHBUART.ST_ADDR1
            case AHBUART.ST_ADDR1:
                self.address |= e << 16
                self.state = AHBUART.ST_ADDR2
            case AHBUART.ST_ADDR2:
                self.address |= e << 8
                self.state = AHBUART.ST_ADDR3
            case AHBUART.ST_ADDR3:
                self.address |= e
                if (self.write_not_read):
                    self.datav = []
                    self.state = AHBUART.ST_DATA0
                else:
                    self.read_cb(self.address, self.length)
                    self.state = AHBUART.ST_CMD
            case AHBUART.ST_DATA0:
                self.data = e << 24
                self.state = AHBUART.ST_DATA1
            case AHBUART.ST_DATA1:
                self.data |= e << 16
                self.state = AHBUART.ST_DATA2
            case AHBUART.ST_DATA2:
                self.data |= e << 8
                self.state = AHBUART.ST_DATA3
            case AHBUART.ST_DATA3:
                self.data |= e
                self.datav.append(self.data)
                self.length -= 1
                if (self.length == 0):
                    self.write_cb(self.address, self.datav)
                    self.state = AHBUART.ST_CMD
                else:
                    self.state = AHBUART.ST_DATA0

if __name__ == "__main__":
    master, slave = os.openpty()
    print(f"UART TTY = {os.ttyname(slave)}")

    ahbjtag0 = AHBJTAG()

    def read_cb(address, length):
        r = ahbjtag0.read(address, length)
        os.write(master, b"".join([x.to_bytes(4, byteorder = "big") for x in r]))

    def write_cb(address, datav):
        ahbjtag0.write(address, datav)

    apbuart0 = AHBUARTParser(read_cb, write_cb)

    def reader():
        for e in os.read(master, 1024):
            apbuart0.step(e)

    loop = asyncio.get_event_loop()
    loop.add_reader(master, reader)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.remove_reader(master)
        loop.close()
        os.close(master)
        os.close(slave)
        protocol.stopEventQueue()
