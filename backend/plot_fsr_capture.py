"""Compare preserved raw frames with the recorded per-cell median filter."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fsr_force import matrix_to_newton, matrix_total

root = Path(__file__).parent / 'recordings/fsr_references/20260909-021811'
data = {'left': [], 'right': []}
errors = []
for path in root.glob('port_*.jsonl'):
    for line in path.read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if 'side' not in row:
            errors.append(row)
            continue
        raw = matrix_total(matrix_to_newton(row['rawAdcValues'], 'raw_adc')[0])
        data[row['side']].append((row['time'], raw, row['total']))
arrays = {side: np.array(sorted(rows)) for side, rows in data.items()}
stats = {}
for side, a in arrays.items():
    dt = np.diff(a[:, 0])
    valid = (dt > .005) & (dt < .15)
    stats[side] = {
        'samples': len(a), 'start_s': float(a[0, 0]), 'end_s': float(a[-1, 0]),
        'median_interval_s': float(np.median(dt)), 'max_gap_s': float(dt.max()),
        'gaps_over_350ms': [[float(a[i, 0]), float(a[i+1, 0]), float(dt[i])] for i in np.where(dt > .35)[0]],
        'raw_range_N_est': [float(a[:, 1].min()), float(a[:, 1].max())],
        'filtered_range_N_est': [float(a[:, 2].min()), float(a[:, 2].max())],
        'raw_median_abs_change': float(np.median(np.abs(np.diff(a[:, 1]))[valid])),
        'filtered_median_abs_change': float(np.median(np.abs(np.diff(a[:, 2]))[valid])),
    }
limit = max(a[:, 1:].max() for a in arrays.values()) * 1.06
end = max(a[-1, 0] for a in arrays.values())
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
for col, name, label in [(1, 'fsr_raw.png', 'CHƯA LỌC'), (2, 'fsr_filtered.png', 'ĐÃ LỌC — trung vị 5 mẫu trên từng ô FSR')]:
    fig, axes = plt.subplots(2, 1, figsize=(15, 7), sharex=True, sharey=True)
    fig.patch.set_facecolor('#f5f7fb')
    for ax, (side, a), color, title in zip(axes, arrays.items(), ['#2563eb', '#e07820'], ['Chân trái', 'Chân phải']):
        t, y = [], []
        for i, row in enumerate(a):
            if i and row[0] - a[i-1, 0] > .35:
                t.append(np.nan); y.append(np.nan)
                ax.axvspan(a[i-1, 0], row[0], color='#ef4444', alpha=.12)
            t.append(row[0]); y.append(row[col])
        ax.plot(t, y, color=color, lw=1.15)
        ax.set_title(title, loc='left', fontweight='bold')
        ax.set_ylabel('Tổng lực ước tính (N)')
        ax.set_ylim(0, limit); ax.set_xlim(0, end)
        ax.grid(alpha=.2)
        ax.spines[['top', 'right']].set_visible(False)
    axes[-1].set_xlabel('Thời gian từ lúc mở ghi (giây) — gồm cả thời gian chờ')
    fig.suptitle('FSR HAI CHÂN | ' + label, fontsize=17, fontweight='bold')
    fig.text(.5, .015, 'Cùng thang đo • Quy đổi lực theo công thức hiện có, chưa xác minh hiệu chuẩn • Vùng đỏ: khoảng nhận mẫu > 0,35 s', ha='center', fontsize=10)
    fig.tight_layout(rect=[0, .04, 1, .94])
    fig.savefig(root / name, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
(root / 'signal_quality.json').write_text(json.dumps({'sides': stats, 'errors': errors}, indent=2), encoding='utf-8')
print(json.dumps(stats, indent=2))
