"""Testa o driver MeowerBoard (BrainFlow compilado) contra tools/meower_sim.py.

Uso:  python test_driver_with_sim.py [tsync|notsync]
Esperado: monotonic True, lost 0, erro do fotodiodo ~0,5-1,5 ms.
"""
import sys, time, subprocess, numpy as np
from pathlib import Path
SIM = Path(__file__).resolve().parents[1] / 'tools' / 'meower_sim.py'
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds, BrainFlowPresets
mode = sys.argv[1] if len(sys.argv) > 1 else 'tsync'
args = [sys.executable, str(SIM), '--ctrl-port', '5620', '--data-port', '5621',
        '--drift-ppm', '40', '--photodiode-period-s', '1.0', '--wifi-jitter-ms', '2']
if mode == 'notsync': args.append('--no-tsync')
sim = subprocess.Popen(args, stdout=subprocess.DEVNULL); time.sleep(1)
p = BrainFlowInputParams(); p.ip_port = 5621; p.ip_port_aux = 5620; p.other_info = 'board_ctrl_port=5720 pga_gain=1 tsync_interval_ms=300'
b = BoardShim(BoardIds.MEOWER_BOARD, p)
try:
    b.prepare_session()
    print('fs cmd:', b.config_board('usr set_sampling_freq 1000'))
    print('clock:', b.config_board('sentir:clock'))
    INFO = b.config_board('sentir:info')
    b.start_stream()
    time.sleep(8)
    d = b.get_board_data(); a = b.get_board_data(preset=BrainFlowPresets.ANCILLARY_PRESET)
    print('clock:', b.config_board('sentir:clock'))
    b.stop_stream()
finally:
    b.release_session(); sim.terminate()
ts = d[17]
print('info:', INFO)
# placa de 8 canais (simulador --ads 1): fotodiodo = bit 0 (GPIO1) do status na linha 23
pd = (d[23].astype(int) & 1) > 0
print('frames', d.shape[1], 'lost', d[22, -1], 'monotonic', bool(np.all(np.diff(ts) > 0)), 'fs~', 1/np.median(np.diff(ts)))
dd=np.diff(ts); bad=np.where(dd<=0)[0]; print("bad idx", bad[:10], dd[bad][:10]*1e3, "first ts diffs", np.round(dd[:5]*1e3,3))
edges = ts[1:][pd[1:] & ~pd[:-1]]; err = (edges - np.round(edges)) * 1e3
print('photodiode edge error ms:', np.round(err, 2))
print('ancillary tsync rows', a.shape, 'median rtt ms', np.median(a[5]) if a.shape[1] else None)
print('uV sample ch0', d[0, :3])
