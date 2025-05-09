import numpy as np
import torch
from typing import Union, Tuple, List, Optional

import scipy as sp
from scipy.fftpack import fft, fftfreq, ifft

def compute_ecdf_features(window_data: Union[np.ndarray, torch.Tensor], n_points: int = 25) -> np.ndarray:
    """
    Feature extraction based on ECDF (Empirical Cumulative Distribution Function)
    
    Args:
        window_data: Input time series data [window_size, channels]  (168, 9)
        n_points: Number of points to extract from each time series (default: 25)
    
    Returns:
        ECDF feature vector of shape [3, (n_points + 1) * 3] with dimensions [3, 78]
        Each axis (x, y, z) contains 3 sensors with n_points (ECDF points + 1 mean value) each
    """
    if isinstance(window_data, torch.Tensor):
        window_data = window_data.detach().cpu().numpy()
    
    channels = window_data.shape[1]
    if channels != 9 and channels != 18:
        raise ValueError(f"Unsupported number of channels: {channels}. Must be 9 (acc only) or 18 (acc+gyro).")
    
    # Use only acc sensors (9 channels)
    if channels == 18:  # If both acc and gyro data exist
        acc_indices = list(range(0, 18, 2))  # Select acc indices only
        window_data = window_data[:, acc_indices]
    
    # Initialize output array: [3 axes, (n_points + 1) features per channel * 3 channels per axis]
    ecdf_features = np.zeros((3, (n_points + 1) * 3))
    
    # Group channels by axes (x, y, z)
    # x축: 0, 3, 6번 채널 (hand, chest, ankle의 x축)
    # y축: 1, 4, 7번 채널 (hand, chest, ankle의 y축)
    # z축: 2, 5, 8번 채널 (hand, chest, ankle의 z축)
    axes_indices = [
        [0, 3, 6],  # x축 (hand_x, chest_x, ankle_x) # axis_channels
        [1, 4, 7],  # y축 (hand_y, chest_y, ankle_y)
        [2, 5, 8]   # z축 (hand_z, chest_z, ankle_z)
    ]
    
    # Process each axis separately
    for axis_idx, axis_channels in enumerate(axes_indices):
        # Process each channel in the current axis
        for i, channel_idx in enumerate(axis_channels):
            # Extract data for current channel
            # (168, 9)
            channel_data = window_data[:, channel_idx]
            # (168,)
            # Calculate mean
            mean_value = np.mean(channel_data)
            
            # Sort data for ECDF
            sorted_data = np.sort(channel_data)
            
            # Select n_points points at equal intervals
            indices = np.around(np.linspace(0, len(sorted_data) - 1, num=n_points)).astype(int)  # (25,)
            ecdf_points = sorted_data[indices]
            
            # Store features for this channel: n_points ECDF points + 1 mean value
            # 각 축(axis_idx)의 i번째 센서에 대한 시작 인덱스 계산
            start_idx = i * (n_points + 1) # 0, 26, 52
            ecdf_features[axis_idx, start_idx:start_idx + n_points] = ecdf_points
            ecdf_features[axis_idx, start_idx + n_points] = mean_value
            
    
    return ecdf_features.astype(np.float32)

def compute_batch_ecdf_features(batch_data: Union[np.ndarray, torch.Tensor]) -> np.ndarray:
    """
    Calculate ECDF features for batch data
    
    Args:
        batch_data: Batch time series data [batch_size, window_size, channels]
    
    Returns:
        Batch ECDF features [batch_size, 3, 78]
        3 axes (x, y, z), each with (n_points+1)*3 = 78 features
    """
    # Convert PyTorch tensor to NumPy if needed
    if isinstance(batch_data, torch.Tensor):
        batch_data = batch_data.detach().cpu().numpy()
        
    batch_size = batch_data.shape[0] # 128
    features = np.zeros((batch_size, 3, 78))  # [batch_size, 3 axes, (n_points+1)*3] = [batch_size, 3, 78]
    
    # 128개의 데이터에 대해 각각 ECDF 특성 계산
    for i in range(batch_size):
        features[i] = compute_ecdf_features(batch_data[i]) # (168, 9) → (3, 78)
    
    return features # (128, 3, 78)

def get_ecdf_dimension() -> tuple:
    """
    Return dimension of ECDF features
    
    Returns:
        Tuple of dimensions (3, 78) - 3 axes, 78 features per axis
    """
    return (3, 78)  # 3 axes × (26 dimensions × 3 sensors per axis)

class Normalizer(object):
    """
    Normalizes dataframe across ALL contained rows (time steps). Different from per-sample normalization.
    """

    def __init__(self, norm_type):
        """
        Args:
            norm_type: choose from:
                "standardization", "minmax": normalizes dataframe across ALL contained rows (time steps)
                "per_sample_std", "per_sample_minmax": normalizes each sample separately (i.e. across only its own rows)
            mean, std, min_val, max_val: optional (num_feat,) Series of pre-computed values
        """

        self.norm_type = norm_type
        
    def fit(self, df):
        if self.norm_type == "standardization":
            self.mean = df.mean(0)
            self.std = df.std(0)
        elif self.norm_type == "minmax":
            self.max_val = df.max()
            self.min_val = df.min()
        elif self.norm_type == "per_sample_std":
            self.max_val = None
            self.min_val = None
        elif self.norm_type == "per_sample_minmax":
            self.max_val = None
            self.min_val = None
        else:
            raise (NameError(f'Normalize method "{self.norm_type}" not implemented'))

    def normalize(self, df):
        """
        Args:
            df: input dataframe
        Returns:
            df: normalized dataframe
        """
        if self.norm_type == "standardization":
            return (df - self.mean) / (self.std + np.finfo(float).eps)

        elif self.norm_type == "minmax":
            return (df - self.min_val) / (self.max_val - self.min_val + np.finfo(float).eps)
        elif self.norm_type == "per_sample_std":
            grouped = df.groupby(by=df.index)
            return (df - grouped.transform('mean')) / grouped.transform('std')
        elif self.norm_type == "per_sample_minmax":
            grouped = df.groupby(by=df.index)
            min_vals = grouped.transform('min')
            return (df - min_vals) / (grouped.transform('max') - min_vals + np.finfo(float).eps)

        else:
            raise (NameError(f'Normalize method "{self.norm_type}" not implemented'))

def components_selection_one_signal(t_signal,freq1,freq2,sampling_freq):
    """
    DC_component: f_signal values having freq between [-0.3 hz to 0 hz] and from [0 hz to 0.3hz] 
                                                                (-0.3 and 0.3 are included)
    
    noise components: f_signal values having freq between [-25 hz to 20 hz[ and from ] 20 hz to 25 hz] 
                                                                  (-25 and 25 hz inculded 20hz and -20hz not included)
    
    selecting body_component: f_signal values having freq between [-20 hz to -0.3 hz] and from [0.3 hz to 20 hz] 
                                                                  (-0.3 and 0.3 not included , -20hz and 20 hz included)
    """

    t_signal=np.array(t_signal)
    t_signal_length=len(t_signal) # number of points in a t_signal
    
    # the t_signal in frequency domain after applying fft
    f_signal=fft(t_signal) # 1D numpy array contains complex values (in C)
    
    # generate frequencies associated to f_signal complex values
    freqs=np.array(sp.fftpack.fftfreq(t_signal_length, d=1/float(sampling_freq))) # frequency values between [-25hz:+25hz]
    

    
    
    f_DC_signal=[] # DC_component in freq domain
    f_body_signal=[] # body component in freq domain numpy.append(a, a[0])
    f_noise_signal=[] # noise in freq domain
    
    for i in range(len(freqs)):# iterate over all available frequencies
        
        # selecting the frequency value
        freq=freqs[i]
        
        # selecting the f_signal value associated to freq
        value= f_signal[i]
        
        # Selecting DC_component values 
        if abs(freq)>freq1:# testing if freq is outside DC_component frequency ranges
            f_DC_signal.append(float(0)) # add 0 to  the  list if it was the case (the value should not be added)                                       
        else: # if freq is inside DC_component frequency ranges 
            f_DC_signal.append(value) # add f_signal value to f_DC_signal list
    
        # Selecting noise component values 
        if (abs(freq)<=freq2):# testing if freq is outside noise frequency ranges 
            f_noise_signal.append(float(0)) # # add 0 to  f_noise_signal list if it was the case 
        else:# if freq is inside noise frequency ranges 
            f_noise_signal.append(value) # add f_signal value to f_noise_signal

        # Selecting body_component values 
        if (abs(freq)<=freq1 or abs(freq)>freq2):# testing if freq is outside Body_component frequency ranges
            f_body_signal.append(float(0))# add 0 to  f_body_signal list
        else:# if freq is inside Body_component frequency ranges
            f_body_signal.append(value) # add f_signal value to f_body_signal list
    
    ################### Inverse the transformation of signals in freq domain ########################
    # applying the inverse fft(ifft) to signals in freq domain and put them in float format
    t_DC_component= ifft(np.array(f_DC_signal)).real
    t_body_component= ifft(np.array(f_body_signal)).real
    #t_noise=ifft(np.array(f_noise_signal)).real
    
    #total_component=t_signal-t_noise # extracting the total component(filtered from noise) 
    #                                 #  by substracting noise from t_signal (the original signal).
    

    #return (total_component,t_DC_component,t_body_component,t_noise) 
    return (t_DC_component,t_body_component) 
