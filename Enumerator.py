import argparse
import glob
import os
import msvcrt
import math
import ffmpeg
import pathlib
from datetime import timedelta
import sys, getpass


def raw_input(value="", end=""):
    sys.stdout.write(value)
    data = getpass.getpass("")
    sys.stdout.write(data)
    sys.stdout.write(end)
    return data


SELECT = "\u001b[47m\u001b[30m"
RESET = "\u001b[0m"


def time(s):
    # tl;dr
    return ("-" if s < 0 else "") + str(timedelta(seconds=abs(s)))


def unzero(s):
    ij: int = 0

    while (c := s[ij]) != ' ':
        if not str.isdigit(c):
            break
        ij += 1
    return s[ij + 1:]


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


parser = argparse.ArgumentParser(prog="Enumerator",
                                 description="Enumerate files in a directory",
                                 epilog="Made by Telthar")

parser.add_argument("path", default=os.getcwd(), nargs='?',
                    help="Path to directory. Defaults to current working dir.")
parser.add_argument("-e", "--ext", type=str, default="*", help="Filter by extension. Defaults to '*'")
parser.add_argument("-D", "--debug", action='store_true', help="Print debug info")
parser.add_argument("-o", "--offset", type=int, default=1, help="Offset of the enumeration. Defaults to 1")
parser.add_argument("--length", action='store_true', help="Calculate audio length, then exit.")

args = parser.parse_args()


class TUI:
    def __init__(self, path, ext="mp3", offset=1):
        self.files = [{
            "path+name": p,
            "name": os.path.basename(p),
            "type": pathlib.Path(p).suffix,
            "audio_length": math.ceil(float(ffmpeg.probe(p)['format']['duration'])) if p.endswith(".mp3") else None
        } for p in glob.glob(os.path.join(path, f"*.{ext}"))]

        self.cursor = 0
        self.drag = -1
        self.message = []

        self.count = len(self.files)
        if self.count == 0:
            print("No matching files found in the directory!")
            exit()

        self.wd = path
        self.ext = ext
        self.used_digits = int(math.log10(self.count)) + 1
        self.offset = offset

        self.TWidth, self.THeight = os.get_terminal_size()

    def display(self):
        start = (self.cursor // (self.THeight - 6)) * (self.THeight - 6)  # 6 is little arbitrary. Amount of LF in infos

        for i, file in enumerate(self.files[start:start + self.THeight - 6]):
            bold = SELECT if (i+start) == self.drag else ''
            curs = '>' if (i+start) == self.cursor else ''

            print(f"{curs}{str(i + self.offset + start).zfill(self.used_digits)}\t"  # >10  [b]Name[/b]
                  f"{bold}{file['name']}" + RESET
                  )

        down = "\\/" if start + self.THeight - 6 < self.count else '=='
        print(f'{down}' + '=' * (self.TWidth - 2), end='\n\n')

        print(f"File count: {self.count} "
              f"| Total size: {convert_size(sum(os.path.getsize(p['path+name']) for p in self.files))}")

        if self.ext == "mp3":
            full = sum(p["audio_length"] for p in self.files)
            print(f"MP3 Length: {time(full)} / ({time(4200 - full)} {int((full / 4200) * 100)}% 70CD) / "
                  f"({time(4800 - full)} {int((full / 4800) * 100)}% 80CD)"
                  )
        else:
            print()     # to keep LF consistent

        print(' | '.join(self.message))
        self.message.clear()
        return self

    def TermConsume(self):
        key = msvcrt.getch()
        if key == b'\xe0':
            key = msvcrt.getch()

            if key == b'P' and self.cursor < self.count - 1:  # down
                self.cursor += 1

                if self.drag != -1:
                    self.files[self.drag], self.files[self.drag + 1] = self.files[self.drag + 1], self.files[self.drag]
                    self.drag += 1
            elif key == b'H' and self.cursor > 0:  # up
                self.cursor -= 1

                if self.drag != -1:
                    self.files[self.drag], self.files[self.drag - 1] = self.files[self.drag - 1], self.files[self.drag]
                    self.drag -= 1
        elif key == b' ':
            self.drag = self.cursor if self.drag == -1 else -1
        elif key == b'\x03' or key == b'\x1b':
            exit()
        elif key == b'\r':
            success = 0

            for i, file in enumerate(self.files):
                new = os.path.join(self.wd, f"{str(i + self.offset).zfill(self.used_digits)} {file['name']}")
                os.rename(file["path+name"], new)
                success += 1
            self.__init__(self.wd, self.ext, self.offset)
            self.message += [f"{success} files affected."]
        elif key == b'\x08':
            for file in self.files:
                os.rename(file["path+name"], os.path.join(self.wd, unzero(file['name'])))
            self.__init__(self.wd, self.ext, self.offset)

        if args.debug:
            self.message += [f"Key '{key}'", f"Cursor {self.cursor}", f"Drag {self.drag}"]

        return self


if __name__ == "__main__":
    if args.length:
        full = sum(p["audio_length"] for p in TUI(args.path, "mp3", args.offset).files)
        print(f"MP3 Length: {time(full)} / ({time(4200 - full)} {int((full / 4200) * 100)}% 70CD) / "
              f"({time(4800 - full)} {int((full / 4800) * 100)}% 80CD)"
              )
        exit()

    tui = TUI(args.path, args.ext, args.offset)
    while True:
        os.system("cls")
        tui.display().TermConsume()
