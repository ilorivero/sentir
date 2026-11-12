#!/usr/bin/env python3
"""Registra o driver MeowerBoard (SENTIR) em um checkout do BrainFlow.

Uso:
    python integrate_meower.py <caminho/para/brainflow>

O script e idempotente: se MEOWER_BOARD ja existir, nada e alterado.
O ID do board e escolhido como (ultimo ID oficial + 1), porque o BrainFlow
valida IDs no intervalo FIRST..LAST. O ID escolhido e impresso no final e
gravado em <brainflow>/MEOWER_BOARD_ID.txt para o backend do SENTIR.

Arquivos alterados no BrainFlow:
  src/utils/inc/brainflow_constants.h        enum BoardIds + LAST
  src/board_controller/board_controller.cpp   include + case no switch
  src/board_controller/build.cmake            fonte + include dir
  src/board_controller/brainflow_boards.cpp   descritor JSON (default + ancillary)
  python_package/brainflow/board_shim.py      enum Python
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "MEOWER_BOARD"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8", newline="\n")


def descriptor(board_id: int) -> str:
    eeg = ", ".join(str(i) for i in range(16))
    names = ",".join(f"CH{i}" for i in range(1, 17))
    return f'''    brainflow_boards_json["boards"]["{board_id}"]["default"] =
    {{
        {{"name", "Meower"}},
        {{"sampling_rate", 1000}}, // nominal; real rate set with "usr set_sampling_freq"
        {{"timestamp_channel", 17}},
        {{"marker_channel", 20}},
        {{"package_num_channel", 19}},
        {{"num_rows", 24}},
        {{"eeg_channels", {{{eeg}}}}},
        {{"eeg_names", "{names}"}},
        {{"battery_channel", 16}},
        // 18 tempo do dispositivo, 21 incerteza de sync, 22 perdas, 23 status do ADS1299 (placa de 8 canais)
        {{"other_channels", {{18, 21, 22, 23}}}}
    }};
    brainflow_boards_json["boards"]["{board_id}"]["ancillary"] =
    {{
        {{"name", "MeowerClockSync"}},
        {{"sampling_rate", 1}},
        {{"timestamp_channel", 7}},
        {{"marker_channel", 8}},
        {{"package_num_channel", 0}},
        {{"num_rows", 9}},
        {{"other_channels", {{1, 2, 3, 4, 5, 6}}}}
    }};
'''


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    root = Path(sys.argv[1]).resolve()
    consts = root / "src/utils/inc/brainflow_constants.h"
    ctrl = root / "src/board_controller/board_controller.cpp"
    cmake = root / "src/board_controller/build.cmake"
    boards = root / "src/board_controller/brainflow_boards.cpp"
    shim = root / "python_package/brainflow/board_shim.py"
    for p in (consts, ctrl, cmake, boards, shim):
        if not p.exists():
            print(f"arquivo nao encontrado: {p}")
            return 1

    s = read(consts)
    if NAME in s:
        m = re.search(rf"{NAME}\s*=\s*(\d+)", s)
        print(f"{NAME} ja registrado (id {m.group(1)}). Nada a fazer.")
        return 0

    # 1. enum BoardIds
    m = re.search(r"LAST\s*=\s*(\w+)", s)
    last_name = m.group(1)
    m2 = re.search(rf"\n(\s*){last_name}\s*=\s*(-?\d+),", s)
    indent, last_id = m2.group(1), int(m2.group(2))
    board_id = last_id + 1
    s = s.replace(m2.group(0), m2.group(0) + f"\n{indent}{NAME} = {board_id},", 1)
    s = re.sub(r"LAST\s*=\s*\w+", f"LAST = {NAME}", s, count=1)
    write(consts, s)

    # 2. copy sources
    dst = root / "src/board_controller/meower"
    (dst / "inc").mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / "meower_board/meower_board.cpp", dst / "meower_board.cpp")
    shutil.copy2(HERE / "meower_board/inc/meower_board.h", dst / "inc/meower_board.h")

    # 3. board_controller.cpp
    s = read(ctrl)
    s = s.replace('#include "synthetic_board.h"',
                  '#include "meower_board.h"\n#include "synthetic_board.h"', 1)
    case_re = re.compile(rf"(        case BoardIds::{last_name}:\n(?:.*\n)*?            break;\n)")
    m = case_re.search(s)
    if not m:
        print("nao achei o case do ultimo board em board_controller.cpp")
        return 1
    new_case = (f"        case BoardIds::{NAME}:\n"
                f"            board = std::shared_ptr<Board> (new MeowerBoard (board_id, params));\n"
                f"            break;\n")
    s = s[:m.end()] + new_case + s[m.end():]
    write(ctrl, s)

    # 4. build.cmake
    s = read(cmake)
    src_line = "    ${CMAKE_CURRENT_SOURCE_DIR}/src/board_controller/meower/meower_board.cpp\n"
    inc_line = "    ${CMAKE_CURRENT_SOURCE_DIR}/src/board_controller/meower/inc\n"
    anchor_src = "    ${CMAKE_CURRENT_SOURCE_DIR}/src/board_controller/synthetic_board.cpp\n"
    if anchor_src not in s:
        print("ancora synthetic_board.cpp nao encontrada em build.cmake")
        return 1
    s = s.replace(anchor_src, anchor_src + src_line, 1)
    anchor_inc = "    ${CMAKE_CURRENT_SOURCE_DIR}/src/board_controller/inc\n"
    s = s.replace(anchor_inc, anchor_inc + inc_line, 1)
    write(cmake, s)

    # 5. descriptor
    s = read(boards)
    anchor = "\nBrainFlowBoards boards_struct;"
    idx = s.find(anchor)
    close = s.rfind("}", 0, idx)
    s = s[:close] + descriptor(board_id) + s[close:]
    write(boards, s)

    # 6. python enum
    s = read(shim)
    m = re.search(rf"\n(\s*){last_name}\s*=\s*{last_id}\s*#:.*", s)
    s = s.replace(m.group(0), m.group(0) + f"\n{m.group(1)}{NAME} = {board_id}  #:", 1)
    write(shim, s)

    (root / "MEOWER_BOARD_ID.txt").write_text(str(board_id))
    print(f"OK: {NAME} = {board_id} registrado em {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
