"""Restored measured-data filters; no amplitude balancing or template curves."""
from collections import deque
import numpy as np


def smooth_camera_segments(values, window=5):
    """Historical median + boxcar, separately for each finite run."""
    result=list(values)
    index=0
    while index<len(values):
        if values[index] is None or not np.isfinite(values[index]):
            result[index]=None;index+=1;continue
        end=index
        while end<len(values) and values[end] is not None and np.isfinite(values[end]):end+=1
        data=np.asarray(values[index:end],dtype=float)
        if len(data)>=window:
            radius=window//2
            padded=np.pad(data,radius,mode='edge')
            median=np.asarray([np.median(padded[n:n+window]) for n in range(len(data))])
            data=np.convolve(np.pad(median,radius,mode='edge'),np.ones(window)/window,mode='valid')
        result[index:end]=np.round(data,4).tolist();index=end
    return result


class FsrMedianFilter:
    def __init__(self):
        self.frames={side:deque(maxlen=5) for side in ('left','right')}
        self.last={}

    def apply(self,side,matrix,timestamp):
        raw=np.asarray(matrix,dtype=float)
        history=self.frames[side]
        if side not in self.last or timestamp-self.last[side]>.35 or timestamp<=self.last[side]:history.clear()
        if history and history[-1].shape!=raw.shape:history.clear()
        history.append(raw.copy());self.last[side]=timestamp
        return np.median(np.stack(history),axis=0).round(2).tolist()
