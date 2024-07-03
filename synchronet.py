import glob
import os
import socket
import time
import json
from ctypes import c_int64
import sys
import pickle
import argparse


parser = argparse.ArgumentParser(
    prog="Synchronet",
    description="A program to synchronize file tree over network. Made by Telthar 2024",
    epilog="Name comes from a BBS client which suppports X/Y/ZModem protocol used to download files over network"
           " (phone line).",

)
parser.add_argument("-p", "--port", dest="port", default=12005, nargs='?', type=int,
                    help="Network port. Change if port 12005 is used.")
parser.add_argument("-d", "--dir", dest="dir", default=os.getcwd(), nargs='?',
                    help="Target directory. Defaults to current working directory.")

parser.add_argument("-r", "--no-remove", action="store_true", default=False, dest="noremove",
                    help="Do not actually remove files marked for deletion. No effect if 'server' mode set.")

subparsers = parser.add_subparsers(dest="mode", required=True, help="Operation mode of this program")

# Subparser for the "client" mode
client_parser = subparsers.add_parser("client", help="Run in client mode")
client_parser.add_argument(
    "address",
    help="Address to connect to in client mode."
)

# Subparser for the "server" mode
server_parser = subparsers.add_parser("server", help="Run in server mode")
# No need to add "address" for the "server" mode

args = parser.parse_args()


def int64(val):
    return c_int64(val).value


CHK_BLOCK = 1024


def checksum(filename: str):
    with open(filename, "rb") as fh:
        start = fh.read(CHK_BLOCK)
        sz = fh.seek(0, os.SEEK_END)
        fh.seek(sz - min(sz, CHK_BLOCK))
        end = fh.read(CHK_BLOCK)

        return int64(int.from_bytes(start, "little") + int.from_bytes(end, "little") + sz)


class File:
    path: str = str()
    checksum: int = int()

    def __init__(self, path: str, pwd: str):
        self.pwd = pwd

        self.path = path
        self.recalculate()

    def recalculate(self):
        try:
            self.checksum = checksum(os.path.join(self.pwd, self.path))
        except PermissionError:
            time.sleep(0.01)
            self.recalculate()

        return self.checksum

    def GetBytes(self) -> bytes:
        with open(os.path.join(self.pwd, self.path), 'rb') as f:
            return f.read()

    def GetCRC(self):
        return [self.path, self.recalculate()]


class FileHandler:
    files: dict[str, File] = {}

    def glorb(self):
        return [os.path.relpath(i, self.root)
                for i in glob.glob(os.path.join(self.root, "**\\*.*"), recursive=True) if os.path.isfile(i)]

    def __init__(self, root: str):
        self.root = root

        for fn in self.glorb():
            self.files[fn] = File(fn, self.root)

    def __getitem__(self, item):
        return self.files[item]

    def recalculate(self):
        now = time.time_ns()

        for pth in set(self.glorb()).difference(self.files.keys()):
            self.files[pth] = File(pth, self.root)
            print(pth)

        rem = []
        for k, v in self.files.items():
            try:
                v.recalculate()
            except FileNotFoundError:
                rem.append(k)

        # Stupid bitch ass python crying you cant remove during iterination
        for k in rem:
            self.files.pop(k)

        print((time.time_ns() - now) / 1_000_000_000, end='\r')
        return self


class SERVER(FileHandler):
    def __init__(self, root: str, sock: socket.socket):
        super().__init__(root)
        self.socket = sock

    def sendCalcs(self):
        d = {
            "Command": "Routine",
            "Files": [i.GetCRC() for i in self.files.values()]
        }
        self.socket.send(json.dumps(d).encode())

        for fn in pickle.loads(self.socket.recv(
                int.from_bytes(self.socket.recv(8), "little", signed=False))):
            with open(os.path.join(self.root, fn), 'rb') as file:
                file.seek(0, os.SEEK_END)
                flen = file.tell()
                file.seek(0)

                self.socket.send(flen.to_bytes(8, "little", signed=False))
                self.socket.send(file.read())

        ajpi = self.socket.getpeername()
        print(f"Client %s (%s) synchronized!" % (
            socket.getnameinfo(ajpi, 0)[0],
            ajpi[0]
        ))

    def __del__(self):
        self.socket.close()


def readUntilJSend(s: socket.socket):
    br = 0
    buf = b''

    while True:
        r = s.recv(1)
        if not r:
            return None

        if r == b'{':
            br += 1
        elif r == b'}':
            br -= 1

        if br == 0:
            return buf + b'}'

        buf += r


class CLIENT(FileHandler):
    def __init__(self, root: str, sock: socket.socket):
        super().__init__(root)
        self.socket = sock
        self.socket.setblocking(True)

    def awaitCMD(self, rm: bool):
        read = readUntilJSend(self.socket)
        if read is None:
            return None

        hashe = json.loads(read)

        toRetrieve = []
        toRemove = []

        if hashe["Command"] == "Routine":
            for d in hashe['Files']:
                fn, crc = d

                if fn not in self.files.keys() or self[fn].checksum != crc:
                    toRetrieve.append(fn)

            for fn in self.files.keys():
                if fn not in [i[0] for i in hashe['Files']]:
                    toRemove.append(fn)

        if rm:
            print("%s files to retrieve, %s marked for deletion." % (len(toRetrieve), len(toRemove)))
        else:
            print("%s files to retrieve." % len(toRetrieve))

        flist = pickle.dumps(toRetrieve)
        self.socket.send(
            len(flist).to_bytes(8, "little", signed=False)
        )
        self.socket.send(flist)

        for fn in toRetrieve:
            print("Downloading %s." % fn)
            fs = int.from_bytes(self.socket.recv(8), "little", signed=False)

            os.makedirs(
                os.path.join(self.root, os.path.dirname(fn)), exist_ok=True
            )
            with open(os.path.join(self.root, fn), "wb") as f:
                f.write(
                    self.socket.recv(fs)
                )

        if len(toRetrieve) > 0:
            print("All files retrieved!")

        if rm and len(toRemove) > 0:
            for fn in toRemove:
                os.remove(os.path.join(self.root, fn))

            print("Unnecessary files removed!")


def client(pwd: str, ip: tuple[str, int], rm: bool):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(ip)
        cli = CLIENT(pwd, sock)

        while cli.awaitCMD(rm) is not None:
            cli.recalculate()


def server(pwd: str, ip: tuple[str, int]):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(ip)
        sock.listen()

        while True:
            conn, addr = sock.accept()
            with conn:
                serv = SERVER(pwd, conn)
                serv.recalculate()
                serv.sendCalcs()
                del serv


if __name__ == "__main__":
    if args.mode == "client":
        client(args.dir, (args.address, args.port), not args.noremove)
    else:
        server(args.dir, ("127.0.0.1", args.port))

