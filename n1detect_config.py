import os
import sys
import logging
import json
from functions.misc import is_number, is_valid_numeric_range, numbers_to_padded_string


def default_config():

    config = dict()
    config['trials'] = dict()
    config['trials']['trial_epoch']                         = (-1.0, 3.0)       # the time-span (in seconds) relative to the stimulus onset that will be used to extract the signal for each trial
    config['trials']['baseline_epoch']                      = (-1.0, -0.1)      # the time-span (in seconds) relative to the stimulus onset that will be considered as the start and end of the baseline epoch within each trial
    config['trials']['baseline_norm']                       = 'median'
    config['trials']['concat_bidirectional_pairs']          = True              # concatenate electrode pairs that were stimulated in both directions (e.g. CH01-CH02 and CH02-CH01)

    config['n1_detect'] = dict()
    config['n1_detect']['peak_search_epoch']                = (0, 0.5)
    config['n1_detect']['n1_search_epoch']                  = (0.009, 0.09)
    config['n1_detect']['n1_baseline_epoch']                = (-1, -0.1)
    config['n1_detect']['n1_baseline_threshold_factor']     = 3.4

    config['visualization'] = dict()
    config['visualization']['lim_epoch']                    = (-0.2, 1)                   # the range for the x-axis in display, (in seconds) relative to the stimulus onset that will be used as the range
    config['visualization']['stim_epoch']                   = (-0.015, 0.0025)            # the range
    config['visualization']['generate_electrode_images']    = True
    config['visualization']['generate_stimpair_images']     = True
    config['visualization']['generate_matrix_images']       = True

    return config


def read_config(filepath):

    # first retrieve a default config
    config = default_config()

    # try to read the JSON configuration file
    try:
        with open(filepath) as json_file:
            json_config = json.load(json_file)
    except IOError as e:
        logging.error('Could not access configuration file at \'' + filepath + '\'')
        return None
    except json.decoder.JSONDecodeError as e:
        logging.error('Could not interpret configuration file at \'' + filepath + '\', make sure the JSON syntax is valid: \'' + str(e) + '\'')
        return None

    #
    # read helper functions
    #

    def retrieve_config_bool(json_dict, ref_config, level1, level2):
        if level1 in json_dict:
            if level2 in json_dict[level1]:
                try:
                    ref_config[level1][level2] = bool(json_dict[level1][level2])
                except:
                    logging.error('Invalid value in the configuration file for ' + level1 + '->' + level2 + ', the value should be a boolean (true, false, 0 or 1)')
                    return False
        return True

    def retrieve_config_number(json_dict, ref_config, level1, level2):
        if level1 in json_dict:
            if level2 in json_dict[level1]:
                if is_number(json_dict[level1][level2]):
                    ref_config[level1][level2] = float(json_dict[level1][level2])
                else:
                    logging.error('Invalid value in the configuration file for ' + level1 + '->' + level2 + ', the value should be a single number')
                    return False
        return True

    def retrieve_config_range(json_dict, ref_config, level1, level2):
        if level1 in json_dict:
            if level2 in json_dict[level1]:
                if is_valid_numeric_range(json_dict[level1][level2]):
                    ref_config[level1][level2] = (json_dict[level1][level2][0], json_dict[level1][level2][1])
                else:
                    logging.error('Invalid value in the configuration file for ' + level1 + '->' + level2 + ', the value should be an array of two numbers')
                    return False
        return True

    def retrieve_config_string(json_dict, ref_config, level1, level2, options=None):
        if level1 in json_dict:
            if level2 in json_dict[level1]:
                if isinstance(json_dict[level1][level2], str):
                    if options is None:
                        ref_config[level1][level2] = json_dict[level1][level2].lower()
                    else:
                        if json_dict[level1][level2].lower() in options:
                            ref_config[level1][level2] = json_dict[level1][level2].lower()
                        else:
                            logging.error('Invalid value in the configuration file for ' + level1 + '->' + level2 + ', the value can only be one of the following options: ' + str(options)[1:-1])
                            return False
                else:
                    logging.error('Invalid value in the configuration file for ' + level1 + '->' + level2 + ', the value should be an array of two numbers')
                    return False
        return True

    #
    # retrieve the settings
    #

    if not retrieve_config_range(json_config, config, 'trials', 'trial_epoch'):
        return None
    if not retrieve_config_range(json_config, config, 'trials', 'baseline_epoch'):
        return None
    if not retrieve_config_string(json_config, config, 'trials', 'baseline_norm', ('median', 'mean', 'none')):
        return None
    if not retrieve_config_bool(json_config, config, 'trials', 'concat_bidirectional_pairs'):
        return None

    if not retrieve_config_range(json_config, config, 'n1_detect', 'peak_search_epoch'):
        return None
    if not retrieve_config_range(json_config, config, 'n1_detect', 'n1_search_epoch'):
        return None
    if not retrieve_config_range(json_config, config, 'n1_detect', 'n1_baseline_epoch'):
        return None
    if not retrieve_config_number(json_config, config, 'n1_detect', 'n1_baseline_threshold_factor'):
        return None

    if not retrieve_config_range(json_config, config, 'visualization', 'lim_epoch'):
        return None
    if not retrieve_config_range(json_config, config, 'visualization', 'stim_epoch'):
        return None
    if not retrieve_config_bool(json_config, config, 'visualization', 'generate_electrode_images'):
        return None
    if not retrieve_config_bool(json_config, config, 'visualization', 'generate_stimpair_images'):
        return None
    if not retrieve_config_bool(json_config, config, 'visualization', 'generate_matrix_images'):
        return None

    #
    return config


def write_config(filepath, config):

    # save the configuration that was used
    config_str = '{\n    "trials": {\n' \
                    '        "trial_epoch":                     [' + numbers_to_padded_string(config['trials']['trial_epoch'], 16) + '],\n' \
                    '        "baseline_epoch":                  [' + numbers_to_padded_string(config['trials']['baseline_epoch'], 16) + '],\n' \
                    '        "baseline_norm":                   "' + config['trials']['baseline_norm'] + '",\n' \
                    '        "concat_bidirectional_pairs":      ' + ('true' if config['trials']['concat_bidirectional_pairs'] else 'false') + '\n' \
                    '    },\n\n' \
                    '    "n1_detect": {\n' \
                    '        "peak_search_epoch":               [' + numbers_to_padded_string(config['n1_detect']['peak_search_epoch'], 16) + '],\n' \
                    '        "n1_search_epoch":                 [' + numbers_to_padded_string(config['n1_detect']['n1_search_epoch'], 16) + '],\n' \
                    '        "n1_baseline_epoch":               [' + numbers_to_padded_string(config['n1_detect']['n1_baseline_epoch'], 16) + '],\n' \
                    '        "n1_baseline_threshold_factor":    ' + str(config['n1_detect']['n1_baseline_threshold_factor']) + '\n' \
                    '    },\n\n' \
                    '    "visualization": {\n' \
                    '        "lim_epoch":                       [' + numbers_to_padded_string(config['visualization']['lim_epoch'], 16) + '],\n' \
                    '        "stim_epoch":                      [' + numbers_to_padded_string(config['visualization']['stim_epoch'], 16) + '],\n' \
                    '        "generate_electrode_images":       ' + ('true' if config['visualization']['generate_electrode_images'] else 'false') + ',\n' \
                    '        "generate_stimpair_images":        ' + ('true' if config['visualization']['generate_stimpair_images'] else 'false') + ',\n' \
                    '        "generate_matrix_images":          ' + ('true' if config['visualization']['generate_matrix_images'] else 'false') + '\n' \
                    '    }\n' \
                    '}'

    with open(filepath, 'w') as json_out:
        json_out.write(config_str + '\n')
        json_out.close()


def check_config(config):

    def check_epoch_within_trial(ref_config, level1, level2):
        if ref_config[level1][level2][0] < config['trials']['trial_epoch'][0]:
            logging.error('Invalid [\'' + level1 + '\'][\'' + level2 + '\'] parameter, the given start-point (at ' + str(ref_config[level1][level2][0]) + 's) lies outside of the trial epoch (' + str(ref_config['trials']['trial_epoch'][0]) + 's - ' + str(ref_config['trials']['trial_epoch'][1]) + 's)')
            return False
        if ref_config[level1][level2][1] > config['trials']['trial_epoch'][1]:
            logging.error('Invalid [\'' + level1 + '\'][\'' + level2 + '\'] parameter, the given end-point (at ' + str(ref_config[level1][level2][1]) + 's) lies outside of the trial epoch (' + str(ref_config['trials']['trial_epoch'][0]) + 's - ' + str(ref_config['trials']['trial_epoch'][1]) + 's)')
            return False
        return True

    def check_range_order(ref_config, level1, level2):
        if ref_config[level1][level2][1] < ref_config[level1][level2][0]:
            logging.error('Invalid [\'' + level1 + '\'][\'' + level2 + '\'] parameter, the given end-point (at ' + str(ref_config[level1][level2][1]) + 's) lies before the start-point (at ' + str(ref_config[level1][level2][0]) + 's)')
            return False
        # TODO: not the same
        return True

    # parameter start-end order
    if not check_range_order(config, 'trials', 'trial_epoch'):
        return False
    if not check_range_order(config, 'trials', 'baseline_epoch'):
        return False
    if not check_range_order(config, 'n1_detect', 'peak_search_epoch'):
        return False
    if not check_range_order(config, 'n1_detect', 'n1_search_epoch'):
        return False
    if not check_range_order(config, 'n1_detect', 'n1_baseline_epoch'):
        return False
    if not check_range_order(config, 'visualization', 'lim_epoch'):
        return False
    if not check_range_order(config, 'visualization', 'stim_epoch'):
        return False

    # N1 epoch parameters should be within trial epoch
    if not check_epoch_within_trial(config, 'n1_detect', 'peak_search_epoch'):
        return False
    if not check_epoch_within_trial(config, 'n1_detect', 'n1_search_epoch'):
        return False
    if not check_epoch_within_trial(config, 'n1_detect', 'n1_baseline_epoch'):
        return False
    if not check_epoch_within_trial(config, 'visualization', 'lim_epoch'):
        return False
    if not check_epoch_within_trial(config, 'visualization', 'stim_epoch'):
        return False

    # trial epoch show start before the stimulus onset (routines in run rely on that)
    if config['trials']['trial_epoch'][0] >= 0:
        logging.error('Invalid [\'trials\'][\'trial_epoch\'] parameter, the epoch should start before the stimulus onset (< 0s)')
        return False

    # N1 peak search should be after stimulus onset
    if config['n1_detect']['peak_search_epoch'][0] < 0:
        logging.error('Invalid [\'n1_detect\'][\'peak_search_epoch\'] parameter, the epoch should start after the stimulus onset (>= 0s)')
        return False
    if config['n1_detect']['n1_search_epoch'][0] < 0:
        logging.error('Invalid [\'n1_detect\'][\'n1_search_epoch\'] parameter, the epoch should start after the stimulus onset (>= 0s)')
        return False

    #
    return True

