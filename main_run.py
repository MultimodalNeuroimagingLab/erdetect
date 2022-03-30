#!/usr/bin/env python3
"""
Early response detection - docker entry-point
=====================================================
Entry-point python script for the automatic detection of early responses (N1) in CCEP data.


Copyright 2022, Max van den Boom (Multimodal Neuroimaging Lab, Mayo Clinic, Rochester MN)

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import sys
import argparse
import os
import logging
from math import isnan, ceil
from glob import glob

from bids_validator import BIDSValidator
import numpy as np
import scipy.io as sio
from matplotlib import cm

from app.config import load_config, write_config, get as cfg, get_config_dict, set as cfg_set, rem as cfg_rem,\
    OUTPUT_IMAGE_SIZE, LOGGING_CAPTION_INDENT_LENGTH, CONFIG_N1DETECT_STD_BASE_BASELINE_EPOCH_DEFAULT, \
    CONFIG_N1DETECT_STD_BASE_BASELINE_THRESHOLD_FACTOR, CONFIG_N1DETECT_CROSS_PROJ_THRESHOLD, CONFIG_N1DETECT_WAVEFORM_PROJ_THRESHOLD
from utils.bids import load_channel_info, load_event_info, load_data_epochs_averages
from utils.IeegDataReader import VALID_FORMAT_EXTENSIONS
from utils.misc import print_progressbar, is_number, CustomLoggingFormatter, multi_line_list, create_figure
from metric_callbacks import metric_cross_proj, metric_waveform
from app.detection import ieeg_detect_n1


#
# version and logging
#

#
__version__ = open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'version')).read()

#
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger_ch = logging.StreamHandler(stream=sys.stdout)
logger_ch.setFormatter(CustomLoggingFormatter())
logger.addHandler(logger_ch)


def log_indented_line(caption, text):
    logging.info(caption.ljust(LOGGING_CAPTION_INDENT_LENGTH, ' ') + text)


#
# define and parse the input arguments
#
parser = argparse.ArgumentParser(description='BIDS App for the automatic detection of early responses (N1) in CCEP data.',
                                 formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('bids_dir',
                    help='The directory with the input dataset formatted according to the BIDS standard.')
parser.add_argument('output_dir',
                    help='The directory where the output files should be stored. If you are running group\n'
                         'level analysis this folder should be prepopulated with the results of the\n'
                         'participant level analysis.')
parser.add_argument('--participant_label',
                    help='The label(s) of the participant(s) that should be analyzed. The label corresponds\n'
                         'to sub-<participant_label> from the BIDS spec (so it does not include "sub-").\n'
                         'If this parameter is not provided all subjects will be analyzed. Multiple\n'
                         'participants can be specified with a space separated list.',
                    nargs="+")
parser.add_argument('--subset_search_pattern',
                    help='The subset(s) of data that should be analyzed. The pattern should be part of a BIDS\n'
                         'compliant folder name (e.g. "task-ccep_run-01"). If this parameter is not provided\n'
                         'all the found subset(s) will be analyzed. Multiple subsets can be specified with\n'
                         'a space separated list.',
                    nargs="+")
parser.add_argument('--format_extension',
                    help='The data format(s) to include. The format(s) should be specified by their\n'
                         'extension (e.g. ".edf"). If this parameter is not provided, then by default\n'
                         'the European Data Format (''.edf''), BrainVision (''.vhdr'', ''.vmrk'', ''.eeg'')\n'
                         'and MEF3 (''.mefd'') formats will be included. Multiple formats can be specified\n'
                         'with a space separated list.',
                    nargs="+")
parser.add_argument('--config_filepath',
                    help='Configures the app according to the settings in the JSON configuration file')
parser.add_argument('--skip_bids_validator',
                    help='Whether or not to perform BIDS data-set validation',
                    action='store_true')
parser.add_argument('--method',
                    help='The method that should be used to determine N1s. the options are:\n'
                         '    - std_base   = The standard deviation of a baseline-epoch is used as a\n'
                         '                   threshold (times a factor) to determine whether the average evoked N1\n'
                         '                   deflection is strong enough. Usage example: ''--method std_base''\n'
                         '    - cross-proj = Cross-projection of the trials is used to determine the inter-trial\n'
                         '                   similarity. A peak with a strong inter-trial similarity is\n'
                         '                   considered N1s. Usage example: ''--method cross-proj''\n'
                         '    - waveform   = Searches for the typical (20Hz oscillation) shape of the average response\n'
                         '                   to determine whether the peak that was found can be considered a N1.\n'
                         '                   Usage example: ''--method waveform'''
                         'Note: If a configuration file is provided, then the method set in this argument will\n'
                         '      overrule the method set in the configuration file',
                    nargs="?")
parser.add_argument('-v', '--version',
                    action='version',
                    version='N1Detection BIDS-App version {}'.format(__version__))

args = parser.parse_args()

#
# display application information
#
log_indented_line('BIDS app:', ('Detect N1 - ' + __version__))
log_indented_line('BIDS input path:', args.bids_dir)
log_indented_line('Output path:', args.output_dir)
if args.config_filepath:
    log_indented_line('Configuration file:', args.config_filepath)
logging.info('')


#
# configure
#

#  read the configuration file (if passed)
if args.config_filepath:
    if not load_config(args.config_filepath):
        logging.error('Could not load the configuration file, exiting...')
        exit(1)

# check for a method argument
if args.method:
    cfg_rem('n1_detect', 'std_base')
    cfg_rem('n1_detect', 'cross_proj')
    cfg_rem('n1_detect', 'waveform')
    if args.method == "std_base":
        cfg_set('std_base', 'n1_detect', 'method')
        cfg_set(CONFIG_N1DETECT_STD_BASE_BASELINE_EPOCH_DEFAULT, 'n1_detect', 'std_base', 'baseline_epoch')
        cfg_set(CONFIG_N1DETECT_STD_BASE_BASELINE_THRESHOLD_FACTOR, 'n1_detect', 'std_base', 'baseline_threshold_factor')
    elif args.method == "cross_proj":
        cfg_set('cross_proj', 'n1_detect', 'method')
        cfg_set(CONFIG_N1DETECT_CROSS_PROJ_THRESHOLD, 'n1_detect', 'cross_proj', 'threshold')
    elif args.method == "waveform":
        cfg_set('waveform', 'n1_detect', 'method')
        cfg_set(CONFIG_N1DETECT_WAVEFORM_PROJ_THRESHOLD, 'n1_detect', 'waveform', 'threshold')
    else:
        logging.error('Invalid method argument \'' + args.method + '\', pick one of the following: \'std_base\', \'cross_proj\' or \'waveform\'')
        exit(1)

# if a metric is used for detection, enable them
if cfg('n1_detect', 'method') == 'cross_proj' and not cfg('metrics', 'cross_proj', 'enabled'):
    logging.warning('N1 detection is set to use cross-projections but the cross-projection metric is disabled, the cross-projection metric will be enabled')
    cfg_set(True, 'metrics', 'cross_proj', 'enabled')
if cfg('n1_detect', 'method') == 'waveform' and not cfg('metrics', 'waveform', 'enabled'):
    logging.warning('N1 detection is set to use waveforms but the waveform metric is disabled, the waveform metric will be enabled')
    cfg_set(True, 'metrics', 'waveform', 'enabled')

# print configuration information
log_indented_line('Trial epoch window:', str(cfg('trials', 'trial_epoch')[0]) + 's < stim onset < ' + str(cfg('trials', 'trial_epoch')[1]) + 's  (window size ' + str(abs(cfg('trials', 'trial_epoch')[1] - cfg('trials', 'trial_epoch')[0])) + 's)')
log_indented_line('Trial out-of-bounds handling:', str(cfg('trials', 'out_of_bounds_handling')))
log_indented_line('Trial baseline window:', str(cfg('trials', 'baseline_epoch')[0]) + 's : ' + str(cfg('trials', 'baseline_epoch')[1]) + 's')
log_indented_line('Trial baseline normalization:', str(cfg('trials', 'baseline_norm')))
log_indented_line('Concatenate bidirectional stimulated pairs:', ('Yes' if cfg('trials', 'concat_bidirectional_pairs') else 'No'))
log_indented_line('Minimum # of required stimulus-pair trials:', str(cfg('trials', 'minimum_stimpair_trials')))
logging.info(multi_line_list(cfg('channels', 'types'), LOGGING_CAPTION_INDENT_LENGTH, 'Channels types:', 20, ' '))
logging.info('')
log_indented_line('Cross-projection metric:', ('Enabled' if cfg('metrics', 'cross_proj', 'enabled') else 'Disabled'))
if cfg('metrics', 'cross_proj', 'enabled'):
    log_indented_line('    Cross-projection epoch:', str(cfg('metrics', 'cross_proj', 'epoch')[0]) + 's : ' + str(cfg('metrics', 'cross_proj', 'epoch')[1]) + 's')
log_indented_line('Waveform metric:', ('Enabled' if cfg('metrics', 'waveform', 'enabled') else 'Disabled'))
if cfg('metrics', 'waveform', 'enabled'):
    log_indented_line('    Waveform epoch:', str(cfg('metrics', 'waveform', 'epoch')[0]) + 's : ' + str(cfg('metrics', 'waveform', 'epoch')[1]) + 's')
    log_indented_line('    Waveform bandpass:', str(cfg('metrics', 'waveform', 'bandpass')[0]) + 'Hz - ' + str(cfg('metrics', 'waveform', 'bandpass')[1]) + 'Hz')
logging.info('')
log_indented_line('Peak search window:', str(cfg('n1_detect', 'peak_search_epoch')[0]) + 's : ' + str(cfg('n1_detect', 'peak_search_epoch')[1]) + 's')
log_indented_line('N1 search window:', str(cfg('n1_detect', 'n1_search_epoch')[0]) + 's : ' + str(cfg('n1_detect', 'n1_search_epoch')[1]) + 's')
log_indented_line('N1 detection method:', str(cfg('n1_detect', 'method')))
if cfg('n1_detect', 'method') == 'std_base':
    log_indented_line('    Std baseline window:', str(cfg('n1_detect', 'std_base', 'baseline_epoch')[0]) + 's : ' + str(cfg('n1_detect', 'std_base', 'baseline_epoch')[1]) + 's')
    log_indented_line('    Std baseline threshold factor:', str(cfg('n1_detect', 'std_base', 'baseline_threshold_factor')))
elif cfg('n1_detect', 'method') == 'cross_proj':
    log_indented_line('    Cross-projection detection threshold:', str(cfg('n1_detect', 'cross_proj', 'threshold')))
elif cfg('n1_detect', 'method') == 'waveform':
    log_indented_line('    Waveform detection threshold:', str(cfg('n1_detect', 'waveform', 'threshold')))
logging.info('')
log_indented_line('Visualization x-axis epoch:', str(cfg('visualization', 'x_axis_epoch')[0]) + 's : ' + str(cfg('visualization', 'x_axis_epoch')[1]) + 's')
log_indented_line('Visualization blank stimulation epoch:', str(cfg('visualization', 'blank_stim_epoch')[0]) + 's : ' + str(cfg('visualization', 'blank_stim_epoch')[1]) + 's')
log_indented_line('Generate electrode images:', ('Yes' if cfg('visualization', 'generate_electrode_images') else 'No'))
log_indented_line('Generate stimulation-pair images:', ('Yes' if cfg('visualization', 'generate_stimpair_images') else 'No'))
log_indented_line('Generate matrix images:', ('Yes' if cfg('visualization', 'generate_matrix_images') else 'No'))
logging.info('')


#
# check if the input is a valid BIDS dataset
#

if not args.skip_bids_validator:
    #process = run_cmd('bids-validator %s' % args.bids_dir)
    #logging.info(process.stdout)
    #if process.returncode != 0:
    #    logging.error('BIDS input dataset did not pass BIDS validator. Datasets can be validated online '
    #                    'using the BIDS Validator (http://incf.github.io/bids-validator/).\nUse the '
    #                    '--skip_bids_validator argument to run the detection without prior BIDS validation.')
    #    exit(1)
    bids_error = False
    for dir_, d, files in os.walk(args.bids_dir):
        for file in files:
            rel_file = os.path.relpath(dir_, args.bids_dir)
            if rel_file[0] == '.':
                rel_file = rel_file[1:]
            rel_file = os.path.join(rel_file, file)
            if not BIDSValidator().is_bids('/' + rel_file):
                logging.error('Invalid BIDS-file: ' + rel_file)
                bids_error = True
    if bids_error:
        logging.error('BIDS input dataset did not pass BIDS validator. Datasets can be validated online '
                      'using the BIDS Validator (http://incf.github.io/bids-validator/).\nUse the '
                      '--skip_bids_validator argument to run the detection without prior BIDS validation.')
        exit(1)

#
# process per subject and subset
#

# make sure the output directory exists
if not os.path.exists(args.output_dir):
    try:
        os.makedirs(args.output_dir)
    except OSError as e:
        logging.error('Could not create output directory (\'' + args.output_dir + '\'), exiting...')
        exit(1)

# list the subject to analyze (either based on the input parameter or list all in the BIDS_dir)
subjects_to_analyze = []
if args.participant_label:

    # user-specified subjects
    subjects_to_analyze = args.participant_label

else:

    # all subjects
    subject_dirs = glob(os.path.join(args.bids_dir, 'sub-*'))
    subjects_to_analyze = [subject_dir.split("-")[-1] for subject_dir in subject_dirs]


#
for subject in subjects_to_analyze:

    # see if the subject is exists (in case the user specified the labels)
    if os.path.isdir(os.path.join(args.bids_dir, subject)):

        # retrieve the data formats to include
        if args.format_extension:
            extensions = args.format_extension
            for extension in extensions:
                if not any(extension in x for x in VALID_FORMAT_EXTENSIONS):
                    logging.error('Invalid data format extension \'' + extension + '\', exiting...')
                    exit(1)
        else:
            extensions = VALID_FORMAT_EXTENSIONS

        # build path patterns for the search of subsets
        subset_patterns = args.subset_search_pattern if args.subset_search_pattern else ('',)
        subsets = []
        modalities = ('*eeg',)                    # ieeg and eeg
        for extension in extensions:
            for modality in modalities:
                for subset_pattern in subset_patterns:
                    subsets += glob(os.path.join(args.bids_dir, subject, modality, '*' + subset_pattern + '*' + extension)) + \
                               glob(os.path.join(args.bids_dir, subject, '*', modality, '*' + subset_pattern + '*' + extension))

        # bring subsets with multiple formats down to one format (prioritized to occurrence in the extension var)
        for subset in subsets:
            subset_name = subset[:subset.rindex(".")]
            for subset_other in reversed(subsets):
                if not subset == subset_other:
                    subset_other_name = subset_other[:subset_other.rindex(".")]
                    if subset_name == subset_other_name:
                        subsets.remove(subset_other)

        # loop through the participant's subsets for analysis
        for subset in subsets:

            # print subset information
            logging.info('------------------------')
            log_indented_line('Subset:', subset)
            logging.info('')

            # derive the bids roots (subject/session and subset) from the full path
            bids_subjsess_root = os.path.commonprefix(glob(os.path.join(os.path.dirname(subset), '*.*')))[:-1]
            bids_subset_root = subset[:subset.rindex('_')]


            #
            # retrieve channel metadata
            #

            # retrieve the channel metadata from the channels.tsv file
            try:
                csv = load_channel_info(bids_subset_root + '_channels.tsv')
            except (FileNotFoundError, LookupError):
                logging.error('Could not load the channel metadata, exiting...')
                exit(1)

            # sort out the good, the bad and the... non-ieeg
            channels_bad = []                                       # channels excluded because they are marked as bad
            channels_incl_detect = []                               # the channel that are needed for detection
            channels_incl_early_reref = []                          # TODO: channel that are included for re-referencing
            channels_excl_detect_by_type = []
            channels_have_status = 'status' in csv.columns
            for index, row in csv.iterrows():
                excluded_for_detection = False

                # check if bad channel
                if channels_have_status:
                    if row['status'].lower() == 'bad':
                        channels_bad.append(row['name'])

                        # continue to the next channel
                        continue

                #
                if not row['type'].upper() in cfg('channels', 'types'):
                    channels_excl_detect_by_type.append(row['name'])
                    excluded_for_detection = True

                if not excluded_for_detection:
                    channels_incl_detect.append(row['name'])

            # print channel information
            logging.info(multi_line_list(channels_bad, LOGGING_CAPTION_INDENT_LENGTH, 'Bad channels (excluded):', 20, ' '))
            logging.info(multi_line_list(channels_excl_detect_by_type, LOGGING_CAPTION_INDENT_LENGTH, 'Channels excluded for detection by type:', 20, ' '))
            logging.info(multi_line_list(channels_incl_detect, LOGGING_CAPTION_INDENT_LENGTH, 'Channels included for detection:', 20, ' ', str(len(channels_incl_detect))))

            # check if there are any channels
            if len(channels_incl_detect) == 0:
                logging.error('No channels were found, exiting...')
                exit(1)
            logging.info('')


            #
            # retrieve events and stimulus-pairs
            #

            # retrieve the stimulation events (onsets and pairs) from the events.tsv file
            try:
                csv = load_event_info(bids_subset_root + '_events.tsv', ('trial_type', 'electrical_stimulation_site'))
            except (FileNotFoundError, LookupError):
                logging.error('Could not load the stimulation event metadata, exiting...')
                exit(1)

            # acquire the onset and electrode-pair for each stimulation
            trial_onsets = []
            trial_pairs = []
            trials_bad_onsets = []
            trials_have_status = 'status' in csv.columns
            for index, row in csv.iterrows():
                if row['trial_type'].lower() == 'electrical_stimulation':
                    if not is_number(row['onset']) or isnan(float(row['onset'])) or float(row['onset']) < 0:
                        logging.warning('Invalid onset \'' + row['onset'] + '\' in events, should be a numeric value >= 0. Discarding trial...')
                        continue

                    if trials_have_status:
                        if not row['status'].lower() == 'good':
                            trials_bad_onsets.append(row['onset'])
                            continue

                    pair = row['electrical_stimulation_site'].split('-')
                    if not len(pair) == 2 or len(pair[0]) == 0 or len(pair[1]) == 0:
                        logging.error('Electrical stimulation site \'' + row['electrical_stimulation_site'] + '\' invalid, should be two values separated by a dash (e.g. CH01-CH02), exiting...')
                        exit(1)
                    trial_onsets.append(float(row['onset']))
                    trial_pairs.append(pair)

            if len(trials_bad_onsets) > 0:
                log_indented_line('Number of trials marked as bad (excluded):', str(len(trials_bad_onsets)))

            # check if there are trials
            if len(trial_onsets) == 0:
                logging.error('No trials were found, exiting...')
                exit(1)


            # determine the stimulation-pairs conditions (and the trial and electrodes that belong to them)
            # (note that the 'concat_bidirectional_pairs' configuration setting is taken into account here)
            #
            stimpair_labels = []                # for each pair, the labels of the electrodes that were stimulated
            stimpair_trial_indices = []         # for each pair, the indices of the trials that were involved
            stimpair_trial_onsets = []          # for each pair, the indices of the trials that were involved
            stimpair_electrode_indices = []     # for each pair, the indices of the electrodes that were stimulated
            for iChannel0 in range(len(channels_incl_detect)):
                for iChannel1 in range(len(channels_incl_detect)):

                    # retrieve the indices of all the trials that concern this stim-pair
                    indices = []
                    if cfg('trials', 'concat_bidirectional_pairs'):
                        # allow concatenation of bidirectional pairs, pair order does not matter
                        if not iChannel1 < iChannel0:
                            # unique pairs while ignoring pair order
                            indices = [i for i, x in enumerate(trial_pairs) if
                                       (x[0] == channels_incl_detect[iChannel0] and x[1] == channels_incl_detect[iChannel1]) or (x[0] == channels_incl_detect[iChannel1] and x[1] == channels_incl_detect[iChannel0])]

                    else:
                        # do not concatenate bidirectional pairs, pair order matters
                        indices = [i for i, x in enumerate(trial_pairs) if
                                   x[0] == channels_incl_detect[iChannel0] and x[1] == channels_incl_detect[iChannel1]]

                    # add the pair if there are trials for it
                    if len(indices) > 0:
                        stimpair_labels.append(channels_incl_detect[iChannel0] + '-' + channels_incl_detect[iChannel1])
                        stimpair_electrode_indices.append((iChannel0, iChannel1))
                        stimpair_trial_indices.append(indices)
                        stimpair_trial_onsets.append([trial_onsets[i] for i in indices])

            # search for stimulus-pairs with too little trials
            stimpair_remove_indices = []
            for iPair in range(len(stimpair_labels)):
                if len(stimpair_trial_indices[iPair]) < cfg('trials', 'minimum_stimpair_trials'):
                    stimpair_remove_indices.append(iPair)
            if len(stimpair_remove_indices) > 0:

                # message
                stimpair_print = [str(stimpair_labels[stimpair_remove_indices[i]]) + ' (' + str(len(stimpair_trial_indices[stimpair_remove_indices[i]])) + ' trials)' for i in range(len(stimpair_remove_indices))]
                stimpair_print = [str_print.ljust(len(max(stimpair_print, key=len)), ' ') for str_print in stimpair_print]
                logging.info(multi_line_list(stimpair_print, LOGGING_CAPTION_INDENT_LENGTH, 'Stim-pairs excluded by number of trials:', 4, '   '))

                # remove those stimulation-pairs
                for index in sorted(stimpair_remove_indices, reverse=True):
                    del stimpair_labels[index]
                    del stimpair_electrode_indices[index]
                    del stimpair_trial_indices[index]
                    del stimpair_trial_onsets[index]

            # display stimulation-pair/trial information
            stimpair_print = [str(stimpair_labels[i]) + ' (' + str(len(stimpair_trial_indices[i])) + ' trials)' for i in range(len(stimpair_labels))]
            stimpair_print = [str_print.ljust(len(max(stimpair_print, key=len)), ' ') for str_print in stimpair_print]
            logging.info(multi_line_list(stimpair_print, LOGGING_CAPTION_INDENT_LENGTH, 'Stimulation pairs included:', 4, '   ', str(len(stimpair_labels))))

            # check if there are stimulus-pairs
            if len(stimpair_labels) == 0:
                logging.error('No stimulus-pairs were found, exiting...')
                exit(1)


            #
            # read and epoch the data
            #

            # determine the metrics that should be produced
            metric_callbacks = tuple()
            if cfg('metrics', 'cross_proj', 'enabled'):
                metric_callbacks += tuple([metric_cross_proj])
            if cfg('metrics', 'waveform', 'enabled'):
                metric_callbacks += tuple([metric_waveform])

            # read, normalize by median and average the trials within the condition
            # Note: 'load_data_epochs_averages' is used instead of 'load_data_epochs' here because it is more memory
            #       efficient when only the averages are needed
            if len(metric_callbacks) == 0:
                logging.info('- Reading data...')
            else:
                logging.info('- Reading data and calculating metrics...')
            # TODO: normalize to raw or to Z-values (return both raw and z?)
            #       z-might be needed for detection
            try:
                sampling_rate, averages, metrics = load_data_epochs_averages(subset, channels_incl_detect, stimpair_trial_onsets,
                                                                             trial_epoch=cfg('trials', 'trial_epoch'),
                                                                             baseline_norm=cfg('trials', 'baseline_norm'),
                                                                             baseline_epoch=cfg('trials', 'baseline_epoch'),
                                                                             out_of_bound_handling=cfg('trials', 'out_of_bounds_handling'),
                                                                             metric_callbacks=metric_callbacks)
            except (ValueError, RuntimeError):
                logging.error('Could not load data (' + subset + '), exiting...')
                exit(1)

            # for each stimulation pair, NaN out the values of the electrodes that were stimulated
            for iPair in range(len(stimpair_labels)):
                averages[stimpair_electrode_indices[iPair][0], iPair, :] = np.nan
                averages[stimpair_electrode_indices[iPair][1], iPair, :] = np.nan

            # determine the sample of stimulus onset (counting from the epoch start)
            onset_sample = int(round(abs(cfg('trials', 'trial_epoch')[0] * sampling_rate)))
            # todo: handle trial epochs which start after the trial onset, currently disallowed by config

            # split out the metric results
            cross_proj_metrics = None
            waveform_metrics = None
            metric_counter = 0
            if cfg('metrics', 'cross_proj', 'enabled'):
                cross_proj_metrics = metrics[:, :, metric_counter]
                metric_counter += 1
            if cfg('metrics', 'waveform', 'enabled'):
                waveform_metrics = metrics[:, :, metric_counter]


            #
            # prepare an output directory
            #

            # make sure a subject directory exists
            output_root = os.path.join(args.output_dir, os.path.basename(os.path.normpath(bids_subset_root)))
            if not os.path.exists(output_root):
                try:
                    os.makedirs(output_root)
                except OSError as e:
                    logging.error("Could not create subset output directory (\'" + output_root + "\'), exiting...")
                    exit(1)

            # intermediate saving of the ccep data as .mat
            saveDict = dict()
            saveDict['sampling_rate'] = sampling_rate
            saveDict['onset_sample'] = onset_sample
            saveDict['ccep_average'] = averages
            saveDict['stimpair_labels'] = np.asarray(stimpair_labels, dtype='object')
            saveDict['channel_labels'] = np.asarray(channels_incl_detect, dtype='object')
            saveDict['config'] = get_config_dict()
            if cfg('metrics', 'cross_proj', 'enabled'):
                saveDict['cross_proj_metrics'] = cross_proj_metrics
            if cfg('metrics', 'waveform', 'enabled'):
                saveDict['waveform_metrics'] = waveform_metrics
            sio.savemat(os.path.join(output_root, 'ccep_data.mat'), saveDict)

            # write the configuration
            write_config(os.path.join(output_root, 'ccep_config.json'))


            #
            # perform the N1 detection
            #

            # detect N1s
            logging.info('- Detecting N1s...')
            n1_peak_indices, n1_peak_amplitudes = ieeg_detect_n1(averages, onset_sample, int(sampling_rate),
                                                                 cross_proj_metrics=cross_proj_metrics,
                                                                 waveform_metrics=waveform_metrics)
            if n1_peak_indices is None or n1_peak_amplitudes is None:
                logging.error('N1 detection failed, exiting...')
                exit(1)

            # intermediate saving of the data and N1 detection as .mat
            saveDict['n1_peak_indices'] = n1_peak_indices
            saveDict['n1_peak_amplitudes'] = n1_peak_amplitudes
            sio.savemat(os.path.join(output_root, 'ccep_data.mat'), saveDict)


            #
            # generate images
            #

            if cfg('visualization', 'generate_electrode_images') or \
                cfg('visualization', 'generate_stimpair_images') or \
                cfg('visualization', 'generate_matrix_images'):

                #
                # prepare some settings for plotting
                #

                # generate the x-axis values
                # Note: TRIAL_EPOCH_START is not expected to start after the stimulus onset, currently disallowed by config
                x = np.arange(averages.shape[2])
                x = x / sampling_rate + cfg('trials', 'trial_epoch')[0]

                # determine the range on the x axis where the stimulus was in samples
                # Note: TRIAL_EPOCH_START is not expected to start after the stimulus onset, currently disallowed by config
                stim_start_x = int(round(abs(cfg('trials', 'trial_epoch')[0] - cfg('visualization', 'blank_stim_epoch')[0]) * sampling_rate)) - 1
                stim_end_x = stim_start_x + int(ceil(abs(cfg('visualization', 'blank_stim_epoch')[1] - cfg('visualization', 'blank_stim_epoch')[0]) * sampling_rate)) - 1

                # calculate the legend x position
                legend_x = cfg('visualization', 'x_axis_epoch')[1] - .13

                # adjust line and font sizes to resolution
                zero_line_thickness = OUTPUT_IMAGE_SIZE / 2000
                signal_line_thickness = OUTPUT_IMAGE_SIZE / 2000
                legend_line_thickness = OUTPUT_IMAGE_SIZE / 500
                title_font_size = round(OUTPUT_IMAGE_SIZE / 80)
                axis_label_font_size = round(OUTPUT_IMAGE_SIZE / 85)
                axis_ticks_font_size = round(OUTPUT_IMAGE_SIZE / 100)
                legend_font_size = round(OUTPUT_IMAGE_SIZE / 90)

                # Adjust the font sizes of the tick according to the number of items (minimum font-size remains 4)
                if len(stimpair_labels) > 36 and axis_ticks_font_size > 4:
                    stimpair_axis_ticks_font_size = 4 + (axis_ticks_font_size - 4) * (36.0 / len(stimpair_labels))
                else:
                    stimpair_axis_ticks_font_size = axis_ticks_font_size
                if len(channels_incl_detect) > 36 and axis_ticks_font_size > 4:
                    electrode_axis_ticks_font_size = 4 + (axis_ticks_font_size - 4) * (36.0 / len(channels_incl_detect))
                else:
                    electrode_axis_ticks_font_size = axis_ticks_font_size

                # account for the situation where there are only a small number of stimulation-pairs.
                if len(stimpair_labels) < 10:
                    stimpair_y_image_height = 500 + (OUTPUT_IMAGE_SIZE - 500) * (len(stimpair_labels) / 10)
                else:
                    stimpair_y_image_height = OUTPUT_IMAGE_SIZE

                # account for a high number of electrodes
                if len(channels_incl_detect) > 50:
                    electrode_y_image_height = 500 + (OUTPUT_IMAGE_SIZE - 500) * (len(channels_incl_detect) / 50)
                else:
                    electrode_y_image_height = OUTPUT_IMAGE_SIZE

                #
                # generate the electrodes plot
                #
                if cfg('visualization', 'generate_electrode_images'):

                    #
                    logging.info('- Generating electrode plots...')

                    # create a progress bar
                    print_progressbar(0, len(channels_incl_detect), prefix='Progress:', suffix='Complete', length=50)

                    # loop through electrodes
                    for iElec in range(len(channels_incl_detect)):

                        # create a figure and retrieve the axis
                        fig = create_figure(OUTPUT_IMAGE_SIZE, stimpair_y_image_height, False)
                        ax = fig.gca()

                        # set the title
                        ax.set_title(channels_incl_detect[iElec] + '\n', fontsize=title_font_size, fontweight='bold')

                        # loop through the stimulation-pairs
                        for iPair in range(len(stimpair_labels)):

                            # draw 0 line
                            y = np.empty((averages.shape[2], 1))
                            y.fill(len(stimpair_labels) - iPair)
                            ax.plot(x, y, linewidth=zero_line_thickness, color=(0.8, 0.8, 0.8))

                            # retrieve the signal
                            y = averages[iElec, iPair, :] / 500
                            y += len(stimpair_labels) - iPair

                            # nan out the stimulation
                            #TODO, only nan if within display range
                            y[stim_start_x:stim_end_x] = np.nan

                            # check if there is a signal to plot
                            if not np.isnan(y).all():

                                # plot the signal
                                ax.plot(x, y, linewidth=signal_line_thickness)

                                # if app is detected, plot it
                                if not isnan(n1_peak_indices[iElec, iPair]):
                                    xN1 = n1_peak_indices[iElec, iPair] / sampling_rate + cfg('trials', 'trial_epoch')[0]
                                    yN1 = n1_peak_amplitudes[iElec, iPair] / 500
                                    yN1 += len(stimpair_labels) - iPair
                                    ax.plot(xN1, yN1, 'bo')

                        # set the x-axis
                        ax.set_xlabel('\ntime (s)', fontsize=axis_label_font_size)
                        ax.set_xlim(cfg('visualization', 'x_axis_epoch'))
                        for label in ax.get_xticklabels():
                            label.set_fontsize(axis_ticks_font_size)

                        # set the y-axis
                        ax.set_ylabel('Stimulated electrode-pair\n', fontsize=axis_label_font_size)
                        ax.set_ylim((0, len(stimpair_labels) + 1))
                        ax.set_yticks(np.arange(1, len(stimpair_labels) + 1, 1))
                        ax.set_yticklabels(np.flip(stimpair_labels), fontsize=stimpair_axis_ticks_font_size)
                        ax.spines['bottom'].set_linewidth(1.5)
                        ax.spines['left'].set_linewidth(1.5)

                        # draw legend
                        legend_y = 2 if len(stimpair_labels) > 4 else (1 if len(stimpair_labels) > 1 else 0)
                        ax.plot([legend_x, legend_x], [legend_y + .05, legend_y + .95], linewidth=legend_line_thickness, color=(0, 0, 0))
                        ax.text(legend_x + .01, legend_y + .3, '500 \u03bcV', fontsize=legend_font_size)

                        # Hide the right and top spines
                        ax.spines['right'].set_visible(False)
                        ax.spines['top'].set_visible(False)

                        # save figure
                        fig.savefig(os.path.join(output_root, 'electrode_' + str(channels_incl_detect[iElec]) + '.png'), bbox_inches='tight')

                        # update progress bar
                        print_progressbar(iElec + 1, len(channels_incl_detect), prefix='Progress:', suffix='Complete', length=50)

                #
                # generate the stimulation-pair plots
                #
                if cfg('visualization', 'generate_stimpair_images'):

                    #
                    logging.info('- Generating stimulation-pair plots...')

                    # create progress bar
                    print_progressbar(0, len(stimpair_labels), prefix='Progress:', suffix='Complete', length=50)

                    # loop through the stimulation-pairs
                    for iPair in range(len(stimpair_labels)):

                        # create a figure and retrieve the axis
                        fig = create_figure(OUTPUT_IMAGE_SIZE, electrode_y_image_height, False)
                        ax = fig.gca()

                        # set the title
                        ax.set_title(stimpair_labels[iPair] + '\n', fontsize=title_font_size, fontweight='bold')

                        # loop through the electrodes
                        for iElec in range(len(channels_incl_detect)):

                            # draw 0 line
                            y = np.empty((averages.shape[2], 1))
                            y.fill(len(channels_incl_detect) - iElec)
                            ax.plot(x, y, linewidth=zero_line_thickness, color=(0.8, 0.8, 0.8))

                            # retrieve the signal
                            y = averages[iElec, iPair, :] / 500
                            y += len(channels_incl_detect) - iElec

                            # nan out the stimulation
                            #TODO, only nan if within display range
                            y[stim_start_x:stim_end_x] = np.nan

                            # plot the signal
                            ax.plot(x, y, linewidth=signal_line_thickness)

                            # if app is detected, plot it
                            if not isnan(n1_peak_indices[iElec, iPair]):
                                xN1 = n1_peak_indices[iElec, iPair] / sampling_rate + cfg('trials', 'trial_epoch')[0]
                                yN1 = n1_peak_amplitudes[iElec, iPair] / 500
                                yN1 += len(channels_incl_detect) - iElec
                                ax.plot(xN1, yN1, 'bo')

                        # set the x-axis
                        ax.set_xlabel('\ntime (s)', fontsize=axis_label_font_size)
                        ax.set_xlim(cfg('visualization', 'x_axis_epoch'))
                        for label in ax.get_xticklabels():
                            label.set_fontsize(axis_ticks_font_size)

                        # set the y-axis
                        ax.set_ylabel('Measured electrodes\n', fontsize=axis_label_font_size)
                        ax.set_ylim((0, len(channels_incl_detect) + 1))
                        ax.set_yticks(np.arange(1, len(channels_incl_detect) + 1, 1))
                        ax.set_yticklabels(np.flip(channels_incl_detect), fontsize=electrode_axis_ticks_font_size)
                        ax.spines['bottom'].set_linewidth(1.5)
                        ax.spines['left'].set_linewidth(1.5)

                        # draw legend
                        legend_y = 2 if len(stimpair_labels) > 4 else (1 if len(stimpair_labels) > 1 else 0)
                        ax.plot([legend_x, legend_x], [legend_y + .05, legend_y + .95], linewidth=legend_line_thickness, color=(0, 0, 0))
                        ax.text(legend_x + .01, legend_y + .3, '500 \u03bcV', fontsize=legend_font_size)

                        # Hide the right and top spines
                        ax.spines['right'].set_visible(False)
                        ax.spines['top'].set_visible(False)

                        # save figure
                        fig.savefig(os.path.join(output_root, 'stimpair_' + str(stimpair_labels[iPair]) + '.png'), bbox_inches='tight')

                        # update progress bar
                        print_progressbar(iPair + 1, len(stimpair_labels), prefix='Progress:', suffix='Complete', length=50)

                #
                # generate the matrices
                #
                if cfg('visualization', 'generate_matrix_images'):

                    #
                    logging.info('- Generating matrices...')

                    # calculate the image width based on the number of stim-pair and electrodes
                    image_width = stimpair_y_image_height / len(stimpair_labels) * len(channels_incl_detect)
                    image_width += 800

                    # make sure the image width does not exceed the matplotlib limit of 2**16
                    if image_width >= 2 ** 16:
                        factor = (2 ** 16 - 50) / image_width
                        image_width = int(round(image_width * factor))
                        image_height = int(round(stimpair_y_image_height * factor))
                    else:
                        image_height = stimpair_y_image_height

                    # adjust the padding between the matrix and the colorbar based on the image width
                    colorbar_padding = 0.01 if image_width < 2000 else (0.01 * (2000 / image_width))

                    # if there are 10 times more electrodes than stimulation-pairs, then allow
                    # the matrix to squeeze horizontally
                    matrix_aspect = 1
                    element_ratio = len(channels_incl_detect) / len(stimpair_labels)
                    if element_ratio > 10:
                        matrix_aspect = element_ratio / 8


                    #
                    # Amplitude matrix
                    #
                    
                    #
                    matrix_amplitudes = n1_peak_amplitudes
                    #matrix_amplitudes[np.isnan(matrix_amplitudes)] = 0
                    matrix_amplitudes *= -1

                    # create a figure and retrieve the axis
                    fig = create_figure(image_width, image_height, False)
                    ax = fig.gca()

                    # create a color map
                    cmap = cm.get_cmap("autumn").copy()
                    cmap.set_bad((.7, .7, .7, 1))

                    # draw the matrix
                    im = ax.imshow(np.transpose(matrix_amplitudes), origin='upper', vmin=0, vmax=500, cmap=cmap, aspect=matrix_aspect)

                    # set labels and ticks
                    ax.set_yticks(np.arange(0, len(stimpair_labels), 1))
                    ax.set_yticklabels(stimpair_labels, fontsize=stimpair_axis_ticks_font_size)
                    ax.set_xticks(np.arange(0, len(channels_incl_detect), 1))
                    ax.set_xticklabels(channels_incl_detect,
                                       rotation=90,
                                       fontsize=stimpair_axis_ticks_font_size)  # deliberately using stimpair-fs here
                    ax.set_xlabel('\nMeasured electrode', fontsize=axis_label_font_size)
                    ax.set_ylabel('Stimulated electrode-pair\n', fontsize=axis_label_font_size)
                    for axis in ['top', 'bottom', 'left', 'right']:
                        ax.spines[axis].set_linewidth(1.5)

                    # set a color-bar
                    cbar = fig.colorbar(im, pad=colorbar_padding)
                    cbar.set_ticks([0, 100, 200, 300, 400, 500])
                    cbar.ax.set_yticklabels(['0', '-100 \u03bcV', '-200 \u03bcV', '-300 \u03bcV', '-400 \u03bcV', '-500 \u03bcV'], fontsize=legend_font_size - 4)
                    cbar.outline.set_linewidth(1.5)

                    # save figure
                    fig.savefig(os.path.join(output_root, 'matrix_amplitude.png'), bbox_inches='tight')


                    #
                    # Latency matrix
                    #

                    # create a figure and retrieve the axis
                    fig = create_figure(image_width, image_height, False)
                    ax = fig.gca()

                    # retrieve the latencies and convert the indices (in samples) to time units (ms)
                    matrix_latencies = n1_peak_indices
                    matrix_latencies -= onset_sample
                    matrix_latencies /= sampling_rate
                    matrix_latencies *= 1000
                    #matrix_latencies[np.isnan(matrix_latencies)] = 0

                    # determine the latest
                    latest_N1 = np.nanmax(matrix_latencies)
                    if np.isnan(latest_N1):
                        latest_N1 = 10
                    latest_N1 = int(ceil(latest_N1 / 10)) * 10

                    # create a color map
                    cmap = cm.get_cmap('summer_r').copy()
                    cmap.set_bad((.7, .7, .7, 1))

                    # draw the matrix
                    im = ax.imshow(np.transpose(matrix_latencies), origin='upper', vmin=0, cmap=cmap, aspect=matrix_aspect)

                    # set labels and ticks
                    ax.set_yticks(np.arange(0, len(stimpair_labels), 1))
                    ax.set_yticklabels(stimpair_labels, fontsize=stimpair_axis_ticks_font_size)
                    ax.set_xticks(np.arange(0, len(channels_incl_detect), 1))
                    ax.set_xticklabels(channels_incl_detect,
                                       rotation=90,
                                       fontsize=stimpair_axis_ticks_font_size)  # deliberately using stimpair-fs here
                    ax.set_xlabel('\nMeasured electrode', fontsize=axis_label_font_size)
                    ax.set_ylabel('Stimulated electrode-pair\n', fontsize=axis_label_font_size)
                    for axis in ['top', 'bottom', 'left', 'right']:
                        ax.spines[axis].set_linewidth(1.5)

                    # generate the legend tick values
                    legend_tick_values = []
                    legend_tick_labels = []
                    for latency in range(0, latest_N1 + 10, 10):
                        legend_tick_values.append(latency)
                        legend_tick_labels.append(str(latency) + ' ms')

                    # set the color limits for the image based on the range display in the legend
                    im.set_clim([legend_tick_values[0], legend_tick_values[-1]])

                    # set a color-bar
                    cbar = fig.colorbar(im, pad=colorbar_padding)
                    cbar.set_ticks(legend_tick_values)
                    cbar.ax.set_yticklabels(legend_tick_labels, fontsize=legend_font_size - 4)
                    cbar.ax.invert_yaxis()
                    cbar.outline.set_linewidth(1.5)

                    # save figure
                    fig.savefig(os.path.join(output_root, 'matrix_latency.png'), bbox_inches='tight')


            #
            logging.info('- Finished subset')

    else:
        #
        logging.warning('Participant \'' + subject + '\' could not be found, skipping')


logging.info('- Finished running')