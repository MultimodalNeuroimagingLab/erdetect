"""
Functions to load BIDS data
=====================================================



Copyright 2022, Max van den Boom (Multimodal Neuroimaging Lab, Mayo Clinic, Rochester MN)

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import logging
import numpy as np
import pandas as pd
from utils.IeegDataReader import IeegDataReader, VALID_FORMAT_EXTENSIONS
from utils.misc import print_progressbar, allocate_array


def load_channel_info(tsv_filepath):

    # retrieve the channel metadata from the channels.tsv file
    try:
        csv = pd.read_csv(tsv_filepath, sep='\t', header=0, encoding='unicode_escape', na_filter=False, dtype=str)
    except FileNotFoundError:
        logging.error('Could not find the file \'' + tsv_filepath + '\'')
        raise FileNotFoundError('Could not find file')

    # check the existence of required columns
    if 'name' not in csv.columns:
        logging.error('Could not find the \'name\' column in \'' + tsv_filepath + '\'')
        raise LookupError('Could not find column')
    if 'type' not in csv.columns:
        logging.error('Could not find the \'type\' column in \'' + tsv_filepath + '\'')
        raise LookupError('Could not find column')
    if 'status' not in csv.columns:
        logging.error('Could not find the \'status\' column in \'' + tsv_filepath + '\'')
        raise LookupError('Could not find column')

    #
    return csv


def load_event_info(tsv_filepath, addition_required_columns=None):

    # retrieve the events from the events.tsv file
    try:
        csv = pd.read_csv(tsv_filepath, sep='\t', header=0, encoding='unicode_escape', na_filter=False, dtype=str)
    except FileNotFoundError:
        logging.error('Could not find the file \'' + tsv_filepath + '\'')
        raise FileNotFoundError('Could not find file')

    # check the existence of required columns
    if 'onset' not in csv.columns:
        logging.error('Could not find the \'onset\' column in \'' + tsv_filepath + '\'')
        raise LookupError('Could not find column')
    if addition_required_columns is not None:
        for column in addition_required_columns:
            if column not in csv.columns:
                logging.error('Could not find the \'' + column + '\' column in \'' + tsv_filepath + '\'')
                raise LookupError('Could not find column')

    #
    return csv


def load_data_epochs(data_path, channels, onsets, trial_epoch=(-1, 3), baseline_norm=None, baseline_epoch=(-1, -0.1), out_of_bound_handling='error', high_pass=None):
    """
    Load and epoch the data into a matrix based on channels, the trial onsets and the epoch range (relative to the onsets)

    Args:
        data_path (str):                Path to the data file or folder
        channels (list or tuple):       The channels that should read from the data, the output will be sorted
                                        according to this input argument.
        onsets (1d list or tuple):      The onsets of the trials around which to epoch the data
        trial_epoch (tuple):            The time-span that will be considered as the signal belonging to a single trial.
                                        Expressed as a tuple with the start- and end-point in seconds relative to
                                        the onset of the trial (e.g. the standard tuple of '-1, 3' will extract
                                        the signal in the period from 1s before the trial onset to 3s after trial onset).
        baseline_norm (None or str):    Baseline normalization setting [None, 'Mean' or 'Median']. If other than None,
                                        normalizes each trial epoch by subtracting the mean or median of part of the
                                        trial (the epoch of the trial indicated in baseline_epoch)
        baseline_epoch (tuple):         The time-span on which the baseline is calculated, expressed as a tuple with the
                                        start- and end-point in seconds relative to the trial onset (e.g. the
                                        standard tuple of '-1, -.1' will use the period from 1s before trial onset
                                        to 100ms before trial onset to calculate the baseline on); this argument
                                        is only used when baseline_norm is set to mean or median
        out_of_bound_handling (str):    Configure the handling of out-of-bound trial epochs;
                                            'error': (default) Throw an error and return when any epoch is out of bound;
                                            'first_last_only': Allows only the first trial epoch to start before the
                                                               data-set and the last trial epoch to end beyond the
                                                               length of the data-set, the trial epochs will be padded
                                                               with NaN values. Note that the first and last trial are
                                                               determined by the first and last entry in the 'onsets'
                                                               parameter, which is not sorted by this function;
                                            'allow':           Allow trial epochs to be out-of-bound, NaNs values will
                                                               be used for part of, or the entire, the trial epoch

    Returns:
        sampling_rate (int or double):  the sampling rate at which the data was acquired
        data (ndarray):                 A three-dimensional array with data epochs per channel (format: channel x
                                        trials/epochs x time); or None when an error occurs

    Note: this function's input arguments are in seconds relative to the trial onsets because the sample rate will
          only be known till after we read the data
    """

    #
    # check input
    #
    try:
        data_reader, baseline_method, out_of_bound_method = __prepare_input(data_path,
                                                                            trial_epoch, baseline_norm, baseline_epoch,
                                                                            out_of_bound_handling)
    except Exception as e:
        logging.error('Error preparing input: ' + str(e))
        raise RuntimeError('Error preparing input')


    #
    # read and process the data
    #
    try:
        
        if data_reader.data_format in (0, 1):
            # EDF or BrainVision format, use MNE to read

            # load the data by iterating over the channels and picking out the epochs, for EDF and BrainVision this is
            # a reasonable options since MNE already loads the entire dataset in memory
            sampling_rate, data = __load_data_epochs__by_channels(  data_reader, channels, onsets,
                                                                    trial_epoch=trial_epoch,
                                                                    baseline_method=baseline_method, baseline_epoch=baseline_epoch,
                                                                    out_of_bound_method=out_of_bound_method)

            if sampling_rate is None or data is None:
                return None, None

        elif data_reader.data_format == 2:
            # MEF3 format

            # load the data by iterating over the epochs, for MEF3 this is the most memory efficient (and likely fastest)
            sampling_rate, data = __load_data_epochs__by_trial(data_reader, channels, onsets,
                                                               trial_epoch=trial_epoch,
                                                               baseline_method=baseline_method, baseline_epoch=baseline_epoch,
                                                               out_of_bound_method=out_of_bound_method)

    except Exception as e:
        logging.error('Error on loading and epoching  data: ' + str(e))
        raise RuntimeError('Error on loading and epoching data')

    #
    data_reader.close()

    #
    return sampling_rate, data


def load_data_epochs_averages(data_path, channels, conditions_onsets, trial_epoch=(-1, 3), baseline_norm=None,
                              baseline_epoch=(-1, -0.1), out_of_bound_handling='error', metric_callbacks=None):
    """
    Load, epoch and return the average for each channel and condition (i.e. the signal in time averaged
    over all trials that belong to the same condition).

    Note: Because this function only has to return the average signal for each channel and condition, it is much more
          memory efficient (this is particularly important when the amount of memory is limited by a Docker or VM)
    Note 2: For the same reason, metric callbacks are implemented here, so while loading, but before averaging, metrics
            can be calculated on subsets of data with minimum memory usage. If memory is not an issue,
            load_data_epochs function can be used to retrieve the full dataset first and then perform calculations.

    Args:
        data_path (str):                      Path to the data file or folder
        channels (list or tuple):             The channels that should read from the data, the output will be sorted
                                              according to this input argument.
        conditions_onsets (2d list or tuple): A two-dimensional list to indicate the conditions, and the onsets
                                              of the trials that belong to each condition.
                                              (format: conditions x condition onsets)
        trial_epoch (tuple):                  The time-span that will be considered as the signal belonging to a single
                                              trial. Expressed as a tuple with the start- and end-point in seconds
                                              relative to onset of the trial (e.g. the standard tuple of '-1, 3' will
                                              extract the signal in the period from 1s before the trial onset to 3s
                                              after the trial onset).
        baseline_norm (None or str):          Baseline normalization setting [None, 'Mean' or 'Median']. If other
                                              than None, normalizes each trial epoch by subtracting the mean or median
                                              of part of the trial (the epoch of the trial indicated in baseline_epoch)
        baseline_epoch (tuple):               The time-span on which the baseline is calculated, expressed as a tuple with
                                              the start- and end-point in seconds relative to the trial onset (e.g. the
                                              standard tuple of '-1, -.1' will use the period from 1s before the trial
                                              onset to 100ms before the trial onset to calculate the baseline on);
                                              this argument is only used when baseline_norm is set to mean or median
        out_of_bound_handling (str):          Configure the handling of out-of-bound trial epochs;
                                                'error': (default) Throw an error and return when any epoch is out of bound;
                                                'first_last_only': Allows only the first trial epoch to start before the
                                                                   data-set and the last trial epoch to end beyond the
                                                                   length of the data-set, the trial epochs will be padded
                                                                   with NaN values. Note that the first and last trial are
                                                                   determined by the first and last entry in the 'onsets'
                                                                   parameter, which is not sorted by this function;
                                                'allow':           Allow trial epochs to be out-of-bound, NaNs values will
                                                                   be used for part of, or the entire, the trial epoch
        metric_callbacks (func or tuple):     Function or tuple of functions that are called to calculate metrics based
                                              on subsets of the un-averaged data. The function(s) are called per
                                              with the following input arguments:
                                                sampling_rate -    The sampling rate of the data
                                                data -             A subset of the data in a 2d array: trials x samples
                                                baseline -         The corresponding baseline values for the trials
                                              If callbacks are defined, a third variable is returned that holds the
                                              return values of the metric callbacks in the format: channel x condition x metric

    Returns:
        sampling_rate (int or double):        The sampling rate at which the data was acquired
        data (ndarray):                       A three-dimensional array with signal averages per channel and condition
                                              (format: channel x condition x samples); or None when an error occurs
        metrics (ndarray):                    If metric callbacks are specified, will return a three-dimensional array
                                              with the metric callback results (format: channel x condition x metric),
                                              else wise None

    Note: this function input arguments are in seconds relative to trial onsets because the sample rate will
          only be known till after we read the data
    """

    #
    # check input
    #
    try:
        data_reader, baseline_method, out_of_bound_method = __prepare_input(data_path,
                                                                            trial_epoch, baseline_norm, baseline_epoch,
                                                                            out_of_bound_handling)
    except Exception as e:
        logging.error('Error preparing input: ' + str(e))
        raise RuntimeError('Error preparing input')


    #
    # read and process the data
    #
    try:

        if data_reader.data_format in (0, 1):
            # EDF or BrainVision format, use MNE to read

            # no per channel manipulations (e.g. high pass filtering etc) are needed before epoching (,metric caluclation) and averaging

            # Load data epoch averages by first iterating over conditions, then over the channels and then retrieve
            # and average (metric) over the epoch-trials within the channel-condition combination
            #
            # Note:     This method is good for EDF and BrainVision because MNE already loads the entire set in memory. So
            #           there is no minimum of loading of data possible.
            sampling_rate, data, metric_values = __load_data_epoch_averages__by_channel_condition_trial(data_reader, channels, conditions_onsets,
                                                                                                        trial_epoch=trial_epoch,
                                                                                                        baseline_method=baseline_method, baseline_epoch=baseline_epoch,
                                                                                                        out_of_bound_method=out_of_bound_method, metric_callbacks=metric_callbacks)

        elif data_reader.data_format == 2:
            # MEF3 format


            # load the data by first iterating over conditions, second over trials within that condition and then
            # retrieve the epoch-data for all channels and take average (and metric) for each channel.
            #
            # For MEF3 this is the fastest solution while using a small amount of memory (because only the required data is loaded)
            #
            sampling_rate, data, metric_values = __load_data_epoch_averages__by_condition_trial(data_reader, channels, conditions_onsets,
                                                                                                trial_epoch=trial_epoch,
                                                                                                baseline_method=baseline_method, baseline_epoch=baseline_epoch,
                                                                                                out_of_bound_method=out_of_bound_method, metric_callbacks=metric_callbacks)

    except Exception as e:
        logging.error('Error on loading, epoching and averaging data: ' + str(e))
        raise RuntimeError('Error on loading, epoching and averaging data')

    #
    data_reader.close()

    # return success
    return sampling_rate, data, metric_values


def __prepare_input(data_path, trial_epoch, baseline_norm, baseline_epoch, out_of_bound_handling):
    """
    Check and prepare the input for loading data
    """

    # data-set format
    data_extension = data_path[data_path.rindex("."):]
    if not any(data_extension in x for x in VALID_FORMAT_EXTENSIONS):
        logging.error('Unknown data format (' + data_extension + ')')
        raise ValueError('Unknown data format (' + data_extension + ')')

    # check trial epoch input
    if trial_epoch[1] < trial_epoch[0]:
        logging.error('Invalid \'trial_epoch\' parameter, the given end-point (at ' + str(trial_epoch[1]) + ') lies before the start-point (at ' + str(trial_epoch[0]) + ')')
        raise ValueError('Invalid \'trial_epoch\' parameter')

    # create and initialize an IEEG data-reader instance to manage the data.
    try:
        data_reader = IeegDataReader(data_path)
        data_reader.init()
    except ValueError:
        raise ValueError('Error upon constructing a data reader')
    except RuntimeError:
        raise RuntimeError('Error upon initializing a data reader')

    # baseline normalization
    baseline_method = 0
    if baseline_norm is not None and len(baseline_norm) > 0:
        if baseline_norm.lower() == 'mean' or baseline_norm.lower() == 'average':
            baseline_method = 1
        elif baseline_norm.lower() == 'median':
            baseline_method = 2
        elif baseline_norm.lower() == 'none':
            baseline_method = 0
        else:
            logging.error('Unknown normalization argument (' + baseline_norm + '), this can only be one of the following options: None, \'mean\' or \'median\'')
            raise ValueError('Unknown normalization argument')

        #
        if baseline_epoch[1] < baseline_epoch[0]:
            logging.error('Invalid \'baseline_epoch\' parameter, the given end-point (at ' + str(baseline_epoch[1]) + ') lies before the start-point (at ' + str(baseline_epoch[0]) + ')')
            raise ValueError('Invalid \'baseline_epoch\' parameter')
        if data_reader.data_format == 2:
            if baseline_epoch[0] < trial_epoch[0]:
                logging.error('Invalid \'baseline_epoch\' parameter, the given baseline start-point (at ' + str(baseline_epoch[0]) + ') lies before the trial start-point (at ' + str(trial_epoch[0]) + ')')
                raise ValueError('Invalid \'baseline_epoch\' parameter')
            if baseline_epoch[1] > trial_epoch[1]:
                logging.error('Invalid \'baseline_epoch\' parameter, the given baseline end-point (at ' + str(baseline_epoch[1]) + ') lies after the trial end-point (at ' + str(trial_epoch[1]) + ')')
                raise ValueError('Invalid \'baseline_epoch\' parameter')

    # out-of-bound handling
    if out_of_bound_handling.lower() == 'first_last_only':
        out_of_bound_method = 1
    elif out_of_bound_handling.lower() == 'allow':
        out_of_bound_method = 2
    elif out_of_bound_handling.lower() == 'error':
        out_of_bound_method = 0
    else:
        logging.error('Unknown out-of-bound handling argument (' + out_of_bound_handling + '), this can only be one of the following options: \'error\', \'first_last_only\' or \'allow\'')
        raise ValueError('Unknown out-of-bound handling argument')

    return data_reader, baseline_method, out_of_bound_method


def __epoch_data__from_channel_data__by_trials(ref_data, channel_idx, channel_data, sampling_rate, onsets, trial_num_samples, trial_epoch, baseline_num_samples, baseline_method, baseline_epoch, out_of_bound_method):
    """
    Epoch the trial-data for a single channel by looping over the trial-onsets
    """

    # loop through the trials
    for trial_idx in range(len(onsets)):

        # calculate the sample indices
        trial_sample_start = int(round((onsets[trial_idx] + trial_epoch[0]) * sampling_rate))
        trial_sample_end = trial_sample_start + trial_num_samples
        baseline_start_sample = int(round((onsets[trial_idx] + baseline_epoch[0]) * sampling_rate))
        baseline_end_sample = baseline_start_sample + baseline_num_samples
        local_start = 0
        local_end = trial_num_samples

        # check whether the trial epoch is within bounds
        if trial_sample_end < 0:
            if (out_of_bound_method == 1 and trial_idx == 0) or out_of_bound_method == 2:
                if channel_idx == 0:
                    logging.warning('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the end of the trial-epoch lies before the start of the data-set.')
                continue
            else:
                logging.error('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the end of the trial-epoch lies before the start of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                raise RuntimeError('Cannot extract trial')
        if trial_sample_start < 0:
            if (out_of_bound_method == 1 and trial_idx == 0) or out_of_bound_method == 2:
                if channel_idx == 0:
                    logging.warning('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the start of the trial-epoch lies before the start of the data-set.')
                local_start = trial_sample_start * -1
                trial_sample_start = 0
            else:
                logging.error('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the start of the trial-epoch lies before the start of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                raise RuntimeError('Cannot extract trial')
        if trial_sample_start > channel_data.size:
            if (out_of_bound_method == 1 and trial_idx == len(onsets) - 1) or out_of_bound_method == 2:
                if channel_idx == 0:
                    logging.warning('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the start of the trial-epoch lies after the end of the data-set.')
                continue
            else:
                logging.error('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the start of the trial-epoch lies after the end of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                raise RuntimeError('Cannot extract trial')
        if trial_sample_end > channel_data.size:
            if (out_of_bound_method == 1 and trial_idx == len(onsets) - 1) or out_of_bound_method == 2:
                if channel_idx == 0:
                    logging.warning('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the end of the trial-epoch lies after the end of the data-set.')
                local_end = trial_num_samples - (trial_sample_end - channel_data.size)
                trial_sample_end = channel_data.size
            else:
                logging.error('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the end of the trial-epoch lies after the end of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                raise RuntimeError('Cannot extract trial')

        # check whether the baseline is within bounds
        if baseline_method > 0:
            if baseline_start_sample < 0 or baseline_end_sample > channel_data.size:
                logging.error('Cannot extract the baseline for the trial with onset ' + str(onsets[trial_idx]) + ', the range for the baseline lies outside of the data')
                raise RuntimeError('Cannot extract the baseline')

        # extract the trial data and perform baseline normalization on the trial if needed
        if baseline_method == 0:
            # TODO: check if owndata, only copy if not (maybe move to IEEGDataReader with parameter)
            #data[channel_idx, trial_idx, local_start:local_end] = channel_data[trial_sample_start:trial_sample_end]
            ref_data[channel_idx, trial_idx, local_start:local_end] = channel_data[trial_sample_start:trial_sample_end].copy()
        elif baseline_method == 1:
            baseline_mean = np.nanmean(channel_data[baseline_start_sample:baseline_end_sample])
            ref_data[channel_idx, trial_idx, local_start:local_end] = channel_data[trial_sample_start:trial_sample_end] - baseline_mean
        elif baseline_method == 2:
            baseline_median = np.nanmedian(channel_data[baseline_start_sample:baseline_end_sample])
            ref_data[channel_idx, trial_idx, local_start:local_end] = channel_data[trial_sample_start:trial_sample_end] - baseline_median

    # return success
    return ref_data


def __load_data_epochs__by_channels(data_reader, channels, onsets, trial_epoch, baseline_method, baseline_epoch, out_of_bound_method):
    """
    Load data epochs to a matrix (format: channel x trials/epochs x time) by iterating over and loading data per channel
    and retrieving the trial-epochs

    Note:   Since this method retrieves the data of a single channel before extracting the epochs, it is reasonably memory
            efficient. It is well suited for EFD or BrainVision since MNE loads the entire set in memory anyway. However,
            when the MEF3 format is used, epoching can be performed even more memory efficient using
            the '__load_data_epochs__by_trial' method (which should be equally fast or even faster)

    Args:
        data_reader (IeegDataReader):   An instance of the IeegDataReader to retrieve metadata and channel data
        channels (list or tuple):       The channels that should read from th
    """

    # calculate the size of the time dimension (in samples)
    trial_num_samples = int(round(abs(trial_epoch[1] - trial_epoch[0]) * data_reader.sampling_rate))
    baseline_num_samples = int(round(abs(baseline_epoch[1] - baseline_epoch[0]) * data_reader.sampling_rate))

    # initialize a data buffer (channel x trials/epochs x time)
    try:
        data = allocate_array((len(channels), len(onsets), trial_num_samples))
    except MemoryError:
        raise MemoryError('Not enough memory create a data output matrix')

    # loop through the included channels
    for channel_idx in range(len(channels)):

        try:

            # retrieve the channel data
            channel_data = data_reader.retrieve_channel_data(channels[channel_idx])

            # epoch the channel data
            __epoch_data__from_channel_data__by_trials(data,
                                                      channel_idx, channel_data, data_reader.sampling_rate,
                                                      onsets, trial_num_samples, trial_epoch,
                                                      baseline_num_samples, baseline_method, baseline_epoch,
                                                      out_of_bound_method)
        except RuntimeError:
            raise RuntimeError('Error upon loading and epoching data')

        #
        del channel_data

    # return the sample rate and the epoched data
    return data_reader.sampling_rate, data


def __load_data_epochs__by_trial(data_reader, channels, onsets, trial_epoch, baseline_method, baseline_epoch, out_of_bound_method):
    """
    Load data epochs to a matrix (format: channel x trials/epochs x time) by looping over and loading data per
    trial (for all channels) and retrieving the trial data by iterating over each of the channels

    Note:   Especially for the MEF3 format this is the most memory efficient because only the minimum amount of data
            is loaded into memory, which should also be faster because less data is read from the disk. For EDF and
            Brainvision there no benefit, since these formats are loaded with MNE, which load the entire dataset into
            memory first.

    Args:
        data_reader (IeegDataReader):   An instance of the IeegDataReader to retrieve metadata and channel data
        channels (list or tuple):       The channels that should read from th
    """

    # calculate the size of the time dimension (in samples)
    trial_num_samples = int(round(abs(trial_epoch[1] - trial_epoch[0]) * data_reader.sampling_rate))
    baseline_num_samples = int(round(abs(baseline_epoch[1] - baseline_epoch[0]) * data_reader.sampling_rate))

    # initialize a data buffer (channel x trials/epochs x time)
    try:
        data = allocate_array((len(channels), len(onsets), trial_num_samples))
    except MemoryError:
        raise MemoryError('Not enough memory create a data output matrix')

    # create progress bar
    print_progressbar(0, len(onsets), prefix='Progress:', suffix='Complete', length=50)

    # loop through the trials
    for trial_idx in range(len(onsets)):

        #
        trial_sample_start = int(round((onsets[trial_idx] + trial_epoch[0]) * data_reader.sampling_rate))
        trial_sample_end = trial_sample_start + trial_num_samples
        baseline_start_sample = int(round((onsets[trial_idx] + baseline_epoch[0]) * data_reader.sampling_rate)) - trial_sample_start
        baseline_end_sample = baseline_start_sample + baseline_num_samples
        local_start = 0
        local_end = trial_num_samples

        # check whether the trial epoch is within bounds
        if trial_sample_end < 0:
            if (out_of_bound_method == 1 and trial_idx == 0) or out_of_bound_method == 2:
                logging.warning('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the end of the trial-epoch lies before the start of the data-set.')
                continue
            else:
                logging.error('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the end of the trial-epoch lies before the start of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                raise RuntimeError('Cannot extract trial')
        if trial_sample_start < 0:
            if (out_of_bound_method == 1 and trial_idx == 0) or out_of_bound_method == 2:
                logging.warning('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the start of the trial-epoch lies before the start of the data-set.')
                local_start = trial_sample_start * -1
                trial_sample_start = 0
            else:
                logging.error('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the start of the trial-epoch lies before the start of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                raise RuntimeError('Cannot extract trial')
        if trial_sample_start > data_reader.num_samples:
            if (out_of_bound_method == 1 and trial_idx == len(onsets) - 1) or out_of_bound_method == 2:
                logging.warning('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the start of the trial-epoch lies after the end of the data-set.')
                continue
            else:
                logging.error('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the start of the trial-epoch lies after the end of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                raise RuntimeError('Cannot extract trial')
        if trial_sample_end > data_reader.num_samples:
            if (out_of_bound_method == 1 and trial_idx == len(onsets) - 1) or out_of_bound_method == 2:
                logging.warning('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the end of the trial-epoch lies after the end of the data-set.')
                local_end = trial_num_samples - (trial_sample_end - data_reader.num_samples)
                trial_sample_end = data_reader.num_samples
            else:
                logging.error('Cannot extract the trial with onset ' + str(onsets[trial_idx]) + ', the end of the trial-epoch lies after the end of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                raise RuntimeError('Cannot extract trial')

        # check whether the baseline is within bounds
        if baseline_method > 0:
            if baseline_start_sample < 0:
                logging.error('Cannot extract the baseline for the trial with onset ' + str(onsets[trial_idx]) + ', the start of the baseline-epoch lies before the start of the trial-epoch')
                raise RuntimeError('Cannot extract baseline')
            if baseline_end_sample > trial_num_samples:
                logging.error('Cannot extract the baseline for the trial with onset ' + str(onsets[trial_idx]) + ', the end of the baseline-epoch lies outside of the trial-epoch')
                raise RuntimeError('Cannot extract baseline')
            if baseline_start_sample < local_start or baseline_end_sample > local_end:
                logging.error('Cannot extract the baseline for the trial with onset ' + str(onsets[trial_idx]) + ', the range for the baseline lies outside of the trial-epoch because that part of the trial-epoch was out-of-bounds')
                raise RuntimeError('Cannot extract baseline')

        # load the trial data
        try:
            trial_data = data_reader.retrieve_sample_range_data(channels, trial_sample_start, trial_sample_end)
        except (RuntimeError, LookupError):
            raise RuntimeError('Could not load data')

        # loop through the channels
        for channel_idx in range(len(channels)):

            # extract the trial data and perform baseline normalization on the trial if needed
            if baseline_method == 0:
                # TODO: check if owndata, only copy if not (maybe move to IEEGDataReader with parameter)
                #data[channel_idx, trial_idx, local_start:local_end] = trial_data[channel_idx]
                data[channel_idx, trial_idx, local_start:local_end] = trial_data[channel_idx].copy()
            elif baseline_method == 1:
                baseline_mean = np.nanmean(trial_data[channel_idx][baseline_start_sample:baseline_end_sample])
                data[channel_idx, trial_idx, local_start:local_end] = trial_data[channel_idx] - baseline_mean
            elif baseline_method == 2:
                baseline_median = np.nanmedian(trial_data[channel_idx][baseline_start_sample:baseline_end_sample])
                data[channel_idx, trial_idx, local_start:local_end] = trial_data[channel_idx] - baseline_median

        # clear temp data
        del trial_data

        # update progress bar
        print_progressbar(trial_idx + 1, len(onsets), prefix='Progress:', suffix='Complete', length=50)

    # return the sample rate and the epoched data
    return data_reader.sampling_rate, data


def __load_data_epoch_averages__by_condition_trial(data_reader, channels, conditions_onsets, trial_epoch, baseline_method, baseline_epoch, out_of_bound_method, metric_callbacks):
    """
    Load data epoch averages to a matrix (format: channel x condition x time) by looping over conditions, looping over
    the trials within a condition and then load the data per condition-trial (for all channels) and perform
    averaging (and metric calculation) by iterating over each of the channels

    Note:   For MEF3 this is the fastest solution while using a small amount of memory (because only the required data
            is loaded). The '__load_data_epoch_averages__by_channel_condition_trial' is even more memory
            efficient but slower for MEF3. For EDF and BrainVision there is not much difference because MNE preloads the
            whole set to memory first, so just numpy-views are returned and used.
    Note2:  only an option when at no point the full channel data is needed (e.g. cannot be used when high-pass filtering is required)
    """


    # calculate the size of the time dimension (in samples)
    trial_num_samples = int(round(abs(trial_epoch[1] - trial_epoch[0]) * data_reader.sampling_rate))
    baseline_num_samples = int(round(abs(baseline_epoch[1] - baseline_epoch[0]) * data_reader.sampling_rate))

    # initialize a data buffer (channel x conditions x samples)
    try:
        data = allocate_array((len(channels), len(conditions_onsets), trial_num_samples))
    except MemoryError:
        raise MemoryError('Not enough memory create a data output matrix')

    # initialize a metric buffer (channel x conditions x metric)
    try:
        metric_values = None
        if metric_callbacks is not None:
            if callable(metric_callbacks):
                metric_values = allocate_array((len(channels), len(conditions_onsets)))
            elif type(metric_callbacks) is tuple and len(metric_callbacks) > 0:
                metric_values = allocate_array((len(channels), len(conditions_onsets), len(metric_callbacks)))
    except MemoryError:
        raise MemoryError('Not enough memory create metric output matrix')

    # create progress bar
    print_progressbar(0, len(conditions_onsets), prefix='Progress:', suffix='Complete', length=50)

    # loop through the conditions
    for condition_idx in range(len(conditions_onsets)):

        # initialize a buffer to put all the data for this condition in (channels x trials x samples)
        try:
            condition_data = allocate_array((len(channels), len(conditions_onsets[condition_idx]), trial_num_samples))
        except MemoryError:
            raise MemoryError('Not enough memory create an condition-data matrix')

        # if baseline normalization is needed and the pre-average callback function is defined, then we first need
        # to accumulate the full (i.e. channels x trials x samples) un-normalized subset to provide to the function.
        # Therefore, we initialize an array to store the baseline values for each channel x trial, so we can normalize
        # after the callback
        baseline_data = None
        if not baseline_method == 0 and metric_callbacks is not None:
            try:
                baseline_data = allocate_array((len(channels), len(conditions_onsets[condition_idx]), baseline_num_samples))
            except MemoryError:
                raise MemoryError('Not enough memory create temporary baseline-data matrix')

        # loop through the trials in the condition
        for trial_idx in range(len(conditions_onsets[condition_idx])):

            # calculate the sample indices
            trial_sample_start = int(round((conditions_onsets[condition_idx][trial_idx] + trial_epoch[0]) * data_reader.sampling_rate))
            trial_sample_end = trial_sample_start + trial_num_samples
            baseline_start_sample = int(round((conditions_onsets[condition_idx][trial_idx] + baseline_epoch[0]) * data_reader.sampling_rate)) - trial_sample_start
            baseline_end_sample = baseline_start_sample + baseline_num_samples
            local_start = 0
            local_end = trial_num_samples

            # check whether the trial epoch is within bounds
            if trial_sample_end < 0:
                if (out_of_bound_method == 1 and condition_idx == 0 and trial_idx == 0) or out_of_bound_method == 2:
                    logging.warning('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the trial-epoch lies before the start of the data-set.')
                    continue
                else:
                    logging.error('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the trial-epoch lies before the start of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                    raise RuntimeError('Cannot extract trial')
            if trial_sample_start < 0:
                if (out_of_bound_method == 1 and condition_idx == 0 and trial_idx == 0) or out_of_bound_method == 2:
                    logging.warning('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the trial-epoch lies before the start of the data-set.')
                    local_start = trial_sample_start * -1
                    trial_sample_start = 0
                else:
                    logging.error('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the trial-epoch lies before the start of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                    raise RuntimeError('Cannot extract trial')
            if trial_sample_start > data_reader.num_samples:
                if (out_of_bound_method == 1 and condition_idx == len(conditions_onsets) - 1 and trial_idx == len(conditions_onsets[condition_idx]) - 1) or out_of_bound_method == 2:
                    logging.warning('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the trial-epoch lies after the end of the data-set.')
                    continue
                else:
                    logging.error('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the trial-epoch lies after the end of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                    raise RuntimeError('Cannot extract trial')
            if trial_sample_end > data_reader.num_samples:
                if (out_of_bound_method == 1 and condition_idx == len(conditions_onsets) - 1 and trial_idx == len(conditions_onsets[condition_idx]) - 1) or out_of_bound_method == 2:
                    logging.warning('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the trial-epoch lies after the end of the data-set.')
                    local_end = trial_num_samples - (trial_sample_end - data_reader.num_samples)
                    trial_sample_end = data_reader.num_samples
                else:
                    logging.error('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the trial-epoch lies after the end of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                    raise RuntimeError('Cannot extract trial')

            # check whether the baseline is within bounds
            if baseline_method > 0:
                if baseline_start_sample < 0:
                    logging.error('Cannot extract the baseline for the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the baseline-epoch lies before the start of the trial-epoch')
                    raise RuntimeError('Cannot extract baseline')
                if baseline_end_sample > trial_num_samples:
                    logging.error('Cannot extract the baseline for the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the baseline-epoch lies outside of the trial-epoch')
                    raise RuntimeError('Cannot extract baseline')
                if baseline_start_sample < local_start or baseline_end_sample > local_end:
                    logging.error('Cannot extract the baseline for the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the range for the baseline lies outside of the trial-epoch because that part of the trial-epoch was out-of-bounds')
                    raise RuntimeError('Cannot extract baseline')

            # load the trial data
            try:
                trial_data = data_reader.retrieve_sample_range_data(channels, trial_sample_start, trial_sample_end)
            except (RuntimeError, LookupError):
                raise RuntimeError('Could not load data')

            # loop through the channels
            for channel_idx in range(len(channels)):

                # extract the trial data and perform baseline normalization on the trial if needed
                #
                # except when there is a function callback. When a callback is then we need to first accumulate the
                # full (i.e. channels x trials x epoch) un-normalized subset to provide to the function, and store
                # the baseline values in a separate array, so they can be applied later
                #
                if baseline_method == 0 or metric_callbacks is not None:
                    # Note: not relevant whether this is a numpy-view or not, since we will average over the trials later
                    condition_data[channel_idx, trial_idx, local_start:local_end] = trial_data[channel_idx]

                if baseline_method == 1:

                    if metric_callbacks is None:
                        # no callback, normalize and store the trial data with baseline applied
                        condition_data[channel_idx, trial_idx, local_start:local_end] = trial_data[channel_idx] - np.nanmean(trial_data[channel_idx][baseline_start_sample:baseline_end_sample])

                    else:
                        # callback, store the baseline values for later use
                        baseline_data[channel_idx, trial_idx, :] = trial_data[channel_idx][baseline_start_sample:baseline_end_sample]

                elif baseline_method == 2:

                    if metric_callbacks is None:
                        # no callback, normalize and store the trial data with baseline applied
                        condition_data[channel_idx, trial_idx, local_start:local_end] = trial_data[channel_idx] - np.nanmedian(trial_data[channel_idx][baseline_start_sample:baseline_end_sample])

                    else:
                        # callback, store the baseline values for later use
                        baseline_data[channel_idx, trial_idx, :] = trial_data[channel_idx][baseline_start_sample:baseline_end_sample]

        # check if a pre-averaging callback function is defined
        metric = None
        if metric_callbacks is not None:

            # per channel, pass the trials x epoch un-normalized subset to the callback function
            # and retrieve the result
            for channel_idx in range(len(channels)):

                if callable(metric_callbacks):

                    # pass the trials x time un-normalized subset to the callback function(s) and store the result
                    metric_value = metric_callbacks(data_reader.sampling_rate,
                                                    condition_data[channel_idx, :, :],
                                                    None if baseline_data is None else baseline_data[channel_idx, :, :])

                    if metric_value is not None:
                        if not np.isscalar(metric_value):
                            logging.error('Return metric is not scalar')
                            raise RuntimeError('Return metric is not scalar')
                        metric_values[channel_idx, condition_idx] = metric_value

                elif type(metric_callbacks) is tuple and len(metric_callbacks) > 0:
                    for iCallback in range(len(metric_callbacks)):
                        if callable(metric_callbacks[iCallback]):

                            # pass the trials x time un-normalized subset to the callback function(s) and store the result
                            metric_value = metric_callbacks[iCallback](data_reader.sampling_rate,
                                                                       condition_data[channel_idx, :, :],
                                                                       None if baseline_data is None else baseline_data[channel_idx, :, :])
                            if metric_value is not None:
                                if not np.isscalar(metric_value):
                                    logging.error('Return metric is not scalar')
                                    raise RuntimeError('Return metric is not scalar')
                                metric_values[channel_idx, condition_idx, iCallback] = metric_value

            # the callback has been made, perform -if needed- the (postponed) normalization with the baseline values
            if baseline_method == 1:
                condition_data -= np.nanmean(baseline_data, axis=2)[:, :, None]
            elif baseline_method == 2:
                condition_data -= np.nanmedian(baseline_data, axis=2)[:, :, None]

        # average the trials for each channel (within this condition) and store the results
        data[:, condition_idx, :] = np.nanmean(condition_data, axis=1)

        # clear reference to data
        del condition_data, trial_data

        # update progress bar
        print_progressbar(condition_idx + 1, len(conditions_onsets), prefix='Progress:', suffix='Complete', length=50)

    # return the sample rate, the average epoch and the metric values (None if not metrics)
    return data_reader.sampling_rate, data, metric_values


def __subload_data_epoch_averages__from_channel__by_condition_trials(ref_data, ref_metric_values, data_reader, channel_idx, channel_name, channel_data, conditions_onsets,
                                                                     trial_num_samples, trial_epoch, baseline_num_samples, baseline_method,
                                                                     baseline_epoch, out_of_bound_method, metric_callbacks):
    """
    Starting from a specific channel, load data epoch averages to an already existing/initialized
    matrix (format: channel x condition x time) by looping over conditions and then within that channel-condition
    combination loop over each of the trials to load the specific channel-condition-trial data.

    ref_data : Reference to the numpy matrix that holds all the epoch averages. Reference is also returned on success
    ref_metric_values: Reference to the ... that holds all the metric values. Reference is also returned on success

    """

    if channel_data is None:
        channel_num_samples = data_reader.num_samples
    else:
        channel_num_samples = channel_data.size

    # loop through the conditions
    for condition_idx in range(len(conditions_onsets)):

        # initialize a buffer to put all the data for this condition-channel in (trials x samples)
        try:
            condition_channel_data = allocate_array((len(conditions_onsets[condition_idx]), trial_num_samples))
        except MemoryError:
            raise MemoryError('Not enough memory create a temporary condition-channel data matrix')

        # if baseline normalization is needed and the pre-average callback function is defined, then we first
        # need to accumulate the full (i.e. channels x trials x epoch) un-normalized subset to provide to the
        # function. Therefore, we initialize an array to store the baseline values for each channel x trial, so
        # we can normalize after the callback
        baseline_data = None
        if not baseline_method == 0 and metric_callbacks is not None:
            try:
                baseline_data = allocate_array((len(conditions_onsets[condition_idx]), baseline_num_samples))
            except MemoryError:
                raise MemoryError('Not enough memory create a temporary condition-channel baseline data matrix')

        # loop through the trials in the condition
        for trial_idx in range(len(conditions_onsets[condition_idx])):

            # calculate the sample indices
            trial_sample_start = int(round((conditions_onsets[condition_idx][trial_idx] + trial_epoch[0]) * data_reader.sampling_rate))
            trial_sample_end = trial_sample_start + trial_num_samples
            baseline_start_sample = int(round((conditions_onsets[condition_idx][trial_idx] + baseline_epoch[0]) * data_reader.sampling_rate))
            baseline_end_sample = baseline_start_sample + baseline_num_samples
            local_start = 0
            local_end = trial_num_samples

            # check whether the trial epoch is within bounds
            if trial_sample_end < 0:
                if (out_of_bound_method == 1 and condition_idx == 0 and trial_idx == 0) or out_of_bound_method == 2:
                    if channel_idx == 0:
                        logging.warning('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the trial-epoch lies before the start of the data-set.')
                    continue
                else:
                    logging.error('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the trial-epoch lies before the start of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                    raise RuntimeError('Cannot extract trial')
            if trial_sample_start < 0:
                if (out_of_bound_method == 1 and condition_idx == 0 and trial_idx == 0) or out_of_bound_method == 2:
                    if channel_idx == 0:
                        logging.warning('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the trial-epoch lies before the start of the data-set.')
                    local_start = trial_sample_start * -1
                    trial_sample_start = 0
                else:
                    logging.error('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the trial-epoch lies before the start of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                    raise RuntimeError('Cannot extract trial')
            if trial_sample_start > channel_num_samples:
                if (out_of_bound_method == 1 and condition_idx == len(conditions_onsets) - 1 and trial_idx == len(
                        conditions_onsets[condition_idx]) - 1) or out_of_bound_method == 2:
                    if channel_idx == 0:
                        logging.warning('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the trial-epoch lies after the end of the data-set.')
                    continue
                else:
                    logging.error('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the start of the trial-epoch lies after the end of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                    raise RuntimeError('Cannot extract trial')
            if trial_sample_end > channel_num_samples:
                if (out_of_bound_method == 1 and condition_idx == len(conditions_onsets) - 1 and trial_idx == len(
                        conditions_onsets[condition_idx]) - 1) or out_of_bound_method == 2:
                    if channel_idx == 0:
                        logging.warning('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the trial-epoch lies after the end of the data-set.')
                    local_end = trial_num_samples - (trial_sample_end - channel_num_samples)
                    trial_sample_end = channel_num_samples
                else:
                    logging.error('Cannot extract the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the end of the trial-epoch lies after the end of the data-set. Use a different out_of_bound_handling argument to allow out-of-bound trial epochs')
                    raise RuntimeError('Cannot extract trial')

            # check whether the baseline is within bounds
            if baseline_method > 0:
                if baseline_start_sample < 0 or baseline_end_sample > channel_num_samples:
                    logging.error('Cannot extract the baseline for the trial with onset ' + str(conditions_onsets[condition_idx][trial_idx]) + ', the range for the baseline lies outside of the data')
                    raise RuntimeError('Cannot extract baseline')

            # extract the trial data
            # check if the channel data is passed or needs to be retrieved
            if channel_data is None:
                # retrieve using reader

                try:
                    trial_baseline_data = data_reader.retrieve_sample_range_data(channel_name, baseline_start_sample, baseline_end_sample)[0]
                    trial_trial_data = data_reader.retrieve_sample_range_data(channel_name, trial_sample_start, trial_sample_end)[0]
                except (RuntimeError, LookupError):
                    raise RuntimeError('Could not load data')

            else:
                # retrieve from passed channel-data

                trial_baseline_data = channel_data[baseline_start_sample:baseline_end_sample]
                trial_trial_data = channel_data[trial_sample_start:trial_sample_end]


            # perform baseline normalization on the trial if needed
            #
            # except when there is a function callback. When a callback is then we need to first accumulate the
            # full (i.e. channels x trials x epoch) un-normalized subset to provide to the function, and store
            # the baseline values in a separate array, so they can be applied later
            #
            if baseline_method == 0 or metric_callbacks is not None:
                condition_channel_data[trial_idx, local_start:local_end] = trial_trial_data

            if baseline_method == 1:

                if metric_callbacks is None:
                    # no callback, normalize and store the trial data with baseline applied
                    condition_channel_data[trial_idx, local_start:local_end] = trial_trial_data - np.nanmean(trial_baseline_data)

                else:
                    # callback, store the baseline values for later use
                    baseline_data[trial_idx, :] = trial_baseline_data

            elif baseline_method == 2:

                if metric_callbacks is None:
                    # no callback, normalize and store the trial data with baseline applied
                    condition_channel_data[trial_idx, local_start:local_end] = trial_trial_data - np.nanmedian(trial_baseline_data)

                else:
                    # callback, store the baseline values for later use
                    baseline_data[trial_idx, :] = trial_baseline_data

        # check if a pre-averaging callback function is defined
        if metric_callbacks is not None:

            if callable(metric_callbacks):

                # pass the trials x epoch un-normalized subset to the callback function(s) and store the result
                metric_value = metric_callbacks(data_reader.sampling_rate, condition_channel_data, baseline_data)
                if metric_value is not None:
                    ref_metric_values[channel_idx, condition_idx] = metric_value

            elif type(metric_callbacks) is tuple and len(metric_callbacks) > 0:
                for iCallback in range(len(metric_callbacks)):
                    if callable(metric_callbacks[iCallback]):

                        # pass the trials x epoch un-normalized subset to the callback function(s) and store the result
                        metric_value = metric_callbacks[iCallback](data_reader.sampling_rate, condition_channel_data, baseline_data)
                        if metric_value is not None:
                            ref_metric_values[channel_idx, condition_idx, iCallback] = metric_value

            # the callback has been made, check if (postponed) normalization should occur based on the baseline
            if baseline_method == 1:
                condition_channel_data -= np.nanmean(baseline_data, axis=1)[:, None]
            elif baseline_method == 2:
                condition_channel_data -= np.nanmedian(baseline_data, axis=1)[:, None]

        # average the trials for each channel (within this condition) and store the results
        ref_data[channel_idx, condition_idx, :] = np.nanmean(condition_channel_data, axis=0)

        # clear reference to data
        del condition_channel_data

    #
    return data_reader.sampling_rate, ref_data, ref_metric_values


def __load_data_epoch_averages__by_channel_condition_trial(data_reader, channels, conditions_onsets, trial_epoch, baseline_method, baseline_epoch, out_of_bound_method, metric_callbacks):
    """
    Load data epoch averages to a matrix (format: channel x condition x time) by looping over channels, then over
    conditions and then within that channel-condition combination loop over each of the trials to load the specific
    channel-condition-trial data. The averaging (and metric calculation) is performed on a temporary matrix in the
    channel loop

    Note:     This function is even more memory efficient than '__load_data_epoch_averages__by_condition_trial', but
              slower for MEF3. For EDF and BrainVision there is not much difference because MNE preloads the
              whole set to memory first, so just numpy-views are returned and used.
    """

    # calculate the size of the time dimension (in samples)
    trial_num_samples = int(round(abs(trial_epoch[1] - trial_epoch[0]) * data_reader.sampling_rate))
    baseline_num_samples = int(round(abs(baseline_epoch[1] - baseline_epoch[0]) * data_reader.sampling_rate))

    # initialize a data buffer (channel x conditions x samples)
    try:
        data = allocate_array((len(channels), len(conditions_onsets), trial_num_samples))
    except MemoryError:
        raise MemoryError('Not enough memory create a data output matrix')

    # initialize a metric buffer (channel x conditions x metric)
    try:
        metric_values = None
        if metric_callbacks is not None:
            if callable(metric_callbacks):
                metric_values = allocate_array((len(channels), len(conditions_onsets)))
            elif type(metric_callbacks) is tuple and len(metric_callbacks) > 0:
                metric_values = allocate_array((len(channels), len(conditions_onsets), len(metric_callbacks)))
    except MemoryError:
        raise MemoryError('Not enough memory create a metric output matrix')

    # create progress bar
    print_progressbar(0, len(conditions_onsets), prefix='Progress:', suffix='Complete', length=50)

    # loop through the channels
    for channel_idx in range(len(channels)):

        #
        try:
            __subload_data_epoch_averages__from_channel__by_condition_trials(data, metric_values,
                                                                             data_reader, channel_idx, channels[channel_idx], None,
                                                                             conditions_onsets, trial_num_samples, trial_epoch,
                                                                             baseline_num_samples, baseline_method, baseline_epoch, out_of_bound_method,
                                                                             metric_callbacks)
        except (MemoryError, RuntimeError):
            raise RuntimeError('Error upon loading, epoching and averaging data')

        # update progress bar
        print_progressbar(channel_idx + 1, len(channels), prefix='Progress:', suffix='Complete', length=50)

    # return the sample rate, the average epoch and the metric values (None if no metrics)
    return data_reader.sampling_rate, data, metric_values