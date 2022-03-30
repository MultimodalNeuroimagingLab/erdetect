"""
Module that contains the function(s) to detect N1 peaks


Copyright 2022, Max van den Boom (Multimodal Neuroimaging Lab, Mayo Clinic, Rochester MN)

Baseline standard deviation based detection method is adapted from:
    Original author: Dorien van Blooijs (2018)
    Adjusted by: Jaap van der Aar, Dora Hermes, Dorien van Blooijs, Giulio Castegnaro; (UMC Utrecht, 2019)

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import logging
import numpy as np
from app.config import get as config
from app.peak_finder import peak_finder


def ieeg_detect_n1(data, stim_onset_index, sampling_rate, cross_proj_metrics=None, waveform_metrics=None):
    """
    Detect the N1 in CCEP data (a matrix of multiple electrodes and stimulation-pairs)

    Args:
        data (ndarray):                     A three-dimensional array with the average signal per electrode and
                                            stimulus-pair (representing: electrodes x stimulation-pairs x time).
        stim_onset_index (int):             the time-point on the input data's time-dimension of stimulation onset (as a
                                            0-based sample-index, all indices before this value are considered pre-stim)
        sampling_rate (int or double):      The sampling rate at which the data was acquired
        cross_proj_metrics (ndarray):
        waveform_metrics (ndarray):


    Returns:
        tuple:                              A tuple containing two ndarrays. Both arrays will be two-dimensional
                                            (representing: electrodes x stimulation-pairs) and match the first two
                                            dimensions of the input. The first ndarray contains the (sample) indices of
                                            the N1s; The second ndarray contains the amplitudes of the N1s.
    """


    #
    # Retrieve detection parameters from the config
    #

    # (tuple) The time-span in which to search for peaks, expressed as a tuple with the  start- and end-point in seconds
    # relative to stimulation onset (e.g. the standard tuple of '0, 0.5' will have the algorithm search for peaks in
    # the period from stimulus onset till 500ms after stimulation onset)
    peak_search_epoch = config('n1_detect', 'peak_search_epoch')

    # (tuple) The time-span in which a app will be searched, expressed as a tuple with the start- and end-point in seconds
    # relative to stimulation onset (e.g. the standard tuple of '0.02, 0.09' will have the algorithm start the search
    # for an app at 20ms after stimulation onset up to 90ms after stimulation onset)
    n1_search_epoch = config('n1_detect', 'n1_search_epoch')

    # (tuple) The time-span in which a app will be searched, expressed as a tuple with the start- and end-point in seconds
    # relative to stimulation onset (e.g. the standard tuple of '0.02, 0.09' will have the algorithm start the search
    # for an app at 20ms after stimulation onset up to 90ms after stimulation onset)
    method = config('n1_detect', 'method')

    if method == 'std_base':

        # (tuple) The time-span on which the baseline is calculated, expressed as a tuple with the start- and end-point in
        # seconds relative to stimulation onset (e.g. the standard tuple of '-1, -.1' will use the period from 1s before
        # stimulation onset to 100ms before stimulation onset to calculate the baseline on)
        baseline_epoch = config('n1_detect', 'std_base', 'baseline_epoch')

        # (double) The factor that is applied to the standard deviation of the baseline amplitude, that defines the
        # threshold which needs to be exceeded to detect a peak (the minimum std is considered 50uV; therefore a factor
        # of 3.4 is recommended to end up with a conservative threshold of 170 uV)
        baseline_threshold_factor = config('n1_detect', 'std_base', 'baseline_threshold_factor')

    elif method == 'cross_proj':

        # (double) The threshold which needs to be exceeded to detect a peak
        cross_proj_threshold = config('n1_detect', 'cross_proj', 'threshold')

    elif method == 'waveform':

        # (double) The threshold which needs to be exceeded to detect a peak
        waveform_threshold = config('n1_detect', 'waveform', 'threshold')


    #
    #
    #

    # retrieve the number of samples
    num_samples = data.shape[2]

    # determine the peak search window in samples
    peak_search_start_sample = int(round(peak_search_epoch[0] * sampling_rate)) + stim_onset_index
    peak_search_end_sample = int(round(peak_search_epoch[1] * sampling_rate)) + stim_onset_index
    if peak_search_end_sample < peak_search_start_sample:
        logging.error('Invalid \'peak_search_epoch\' parameter, the given end-point (at ' + str(peak_search_epoch[1]) + ') lies before the start-point (at t = ' + str(peak_search_epoch[0]) + ')')
        return None, None
    if peak_search_end_sample > num_samples:
        logging.error('The data epoch is not big enough, the peak window requires at least ' + str(stim_onset_index + abs(peak_search_start_sample)) + ' samples after stimulation onset')
        return None, None

    # determine the start- and end-point (in samples) of the time-span in which to search for a N1
    n1_search_start_sample = int(round(n1_search_epoch[0] * sampling_rate)) + stim_onset_index
    n1_search_end_sample = int(round(n1_search_epoch[1] * sampling_rate)) + stim_onset_index
    if n1_search_end_sample < n1_search_start_sample:
        logging.error('Invalid \'n1_search_epoch\' parameter, the given end-point (at ' + str(n1_search_epoch[1]) + ') lies before the start-point (at t = ' + str(n1_search_epoch[0]) + ')')
        return None, None

    # initialize an output buffer (electrode x stimulation-pair)
    n1_peak_indices = np.empty((data.shape[0], data.shape[1]))
    n1_peak_indices.fill(np.nan)
    n1_peak_amplitudes = np.empty((data.shape[0], data.shape[1]))
    n1_peak_amplitudes.fill(np.nan)

    # check method and corresponding input
    if method == 'std_base':

        # determine the std baseline range in samples
        baseline_start_sample = int(round(baseline_epoch[0] * sampling_rate)) + stim_onset_index
        baseline_end_sample = int(round(baseline_epoch[1] * sampling_rate)) + stim_onset_index

    elif method == 'waveform':

        if waveform_metrics is None:
            logging.error('Method is set to \'waveform\' but no waveform-metrics were passed to the detection function')
            return None, None
        elif not waveform_metrics.shape == n1_peak_indices.shape:
            logging.error('Size of the waveform-metrics matrix does not match the size of the output buffer (the number of electrodes and stim-pairs do not match)')
            return None, None

    elif method == 'cross_proj':

        if waveform_metrics is None:
            logging.error('Method is set to \'cross_proj\' but no cross-projection metrics were passed to the detection function')
            return None, None
        elif not waveform_metrics.shape == n1_peak_indices.shape:
            logging.error('Size of the cross-projection metrics matrix does not match the size of the output buffer (the number of electrodes and stim-pairs do not match)')
            return None, None

    # for every electrode
    for iElec in range(data.shape[0]):

        # for every stimulation-pair
        for iPair in range(data.shape[1]):

            # retrieve the part of the signal to search for peaks in
            signal = data[iElec, iPair, peak_search_start_sample + 1:peak_search_end_sample]

            # continue if all are nan (the case when the stim-electrodes are nan-ed out on the electrode dimensions)
            if np.all(np.isnan(signal)):
                continue

            # peak_finder is not robust against incidental nans, make 0
            signal[np.isnan(signal)] = 0

            # use peak_finder function to find the negative peak indices and their amplitude
            (neg_inds, neg_mags) = peak_finder(signal,
                                               sel=20,  # num of samples around a peak not considered as another peak
                                               thresh=None,
                                               extrema=-1,
                                               include_endpoints=True,
                                               interpolate=False)

            # if a peak is found on the first sample, then that is not an actual peak, remove
            if neg_inds is not None and len(neg_inds) > 0 and neg_inds[0] == 0:
                neg_inds = np.delete(neg_inds, 0)
                neg_mags = np.delete(neg_mags, 0)

            # if there are no peaks, continue to next
            if neg_inds is None or len(neg_inds) == 0:
                continue

            # shift the indices to align with the full epoch (not the subsection that was passed to the peak_finder)
            neg_inds = neg_inds + peak_search_start_sample

            # keep the peaks within the app search range, or continue if there are none
            in_range = (neg_inds >= n1_search_start_sample) & (neg_inds <= n1_search_end_sample)
            if any(in_range):
                neg_inds = neg_inds[in_range]
                neg_mags = neg_mags[in_range]
            else:
                continue

            # find the index of the first peak maximum
            max_ind = np.where(abs(neg_mags) == np.max(abs(neg_mags)))[0][0]

            # make sure the peak is negative, else wise continue to next
            if neg_mags[max_ind] > 0:
                continue

            # make sure the signal is not saturated, continue to next if it is
            if abs(neg_mags[max_ind]) > 3000:
                continue

            #
            # Determine whether peak can be considered a N1 (by the peak or by other metrics)
            #

            if method == 'cross_proj':

                # classify as an N1 on threshold, store the peak (index and amplitude)
                if cross_proj_metrics[iElec, iPair] > cross_proj_threshold:
                    n1_peak_indices[iElec, iPair] = neg_inds[max_ind]
                    n1_peak_amplitudes[iElec, iPair] = neg_mags[max_ind]

            elif method == 'waveform':

                # classify as an N1 on threshold, store the peak (index and amplitude)
                if waveform_metrics[iElec, iPair] > waveform_threshold:
                    n1_peak_indices[iElec, iPair] = neg_inds[max_ind]
                    n1_peak_amplitudes[iElec, iPair] = neg_mags[max_ind]

            else:
                # Detection by baseline std

                # retrieve the baseline
                # Note: check all nans; which is often the case when the stimulated electrodes are nan-ed out
                #       on the electrode dimensions, just continue to next
                baseline_signal = data[iElec, iPair, baseline_start_sample:baseline_end_sample]
                if np.all(np.isnan(baseline_signal)):
                    continue

                # calculate the std of the baseline samples
                baseline_std = np.nanstd(baseline_signal)

                # make sure the baseline_std is not smaller than 50uV (this value was validated by Jaap)
                if baseline_std < 50:
                    baseline_std = 50

                # check if the peak value does not exceed the baseline standard deviation time a factor
                if abs(neg_mags[max_ind]) >= baseline_threshold_factor * abs(baseline_std):

                    # classify as an N1, store the peak (index and amplitude)
                    n1_peak_indices[iElec, iPair] = neg_inds[max_ind]
                    n1_peak_amplitudes[iElec, iPair] = neg_mags[max_ind]

    # pass results back
    return n1_peak_indices, n1_peak_amplitudes
