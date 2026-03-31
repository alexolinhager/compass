"""
Restart ensemble test case for SGH template.

This test case identifies incomplete runs from a spinup ensemble and sets up
restart steps for them. Each restart step continues the simulation from the
last checkpoint.

Usage:
    compass setup -t landice/ensemble_generator/sgh_restart_ensemble
        -w /work/restart -f restart_ensemble.cfg
    compass run -w /work/restart
"""

import json
import os

import compass.namelist
from compass.landice.tests.ensemble_generator.ensemble_manager import (
    EnsembleManager,
)
from compass.testcase import TestCase

from .restart_member import InPlaceRestartMember


class RestartEnsemble(TestCase):
    """
    A test case for restarting incomplete ensemble members.

    This identifies runs from a spinup_ensemble that did not complete
    and continues them from their last checkpoint, using the run list
    from a required analysis_summary.json file.
    """

    def __init__(self, test_group):
        """
        Create the restart ensemble test case

        Parameters
        ----------
        test_group : compass test group
            The test group that this test case belongs to
        """
        name = 'sgh_restart_ensemble'
        super().__init__(test_group=test_group, name=name)

        # Add the ensemble manager (handles job submission)
        self.add_step(EnsembleManager(test_case=self))

    def configure(self):
        """
        Configure restart ensemble by identifying incomplete runs.

        This method:
        1. Reads spinup_work_dir and analysis_summary_file from config
        2. Loads restart candidates from analysis_summary_file
        3. Creates RestartMember steps for runs needing continuation
        4. Sets up ensemble_manager to handle job submission
        """
        config = self.config

        # Required: spinup_work_dir
        try:
            spinup_work_dir = config.get('restart_ensemble', 'spinup_work_dir')
        except Exception:
            raise ValueError(
                "restart_ensemble config must specify spinup_work_dir\n"
                "[restart_ensemble]\n"
                "spinup_work_dir = /path/to/spinup/ensemble"
            )
        if not os.path.exists(spinup_work_dir):
            raise ValueError(f"spinup_work_dir not found: {spinup_work_dir}")

        # Required: analysis_summary_file
        try:
            analysis_summary_file = config.get('restart_ensemble',
                                               'analysis_summary_file')
        except Exception:
            raise ValueError(
                "restart_ensemble config must specify analysis_summary_file\n"
                "[restart_ensemble]\n"
                "analysis_summary_file = /path/to/analysis_summary.json"
            )
        if not os.path.exists(analysis_summary_file):
            raise ValueError(
                f"analysis_summary_file not found: {analysis_summary_file}")

        # Load restart candidates from summary
        with open(analysis_summary_file, 'r') as f:
            summary = json.load(f)
        restart_needed_runs = summary.get('restart_needed_runs', [])
        print(f"Found {len(restart_needed_runs)} restart candidates in "
              f"{analysis_summary_file}")

        # Optional config
        try:
            max_consecutive_restarts = config.getint(
                'restart_ensemble', 'max_consecutive_restarts')
        except Exception:
            max_consecutive_restarts = 3

        try:
            auto_restart = config.getboolean(
                'restart_ensemble', 'auto_restart_incomplete')
        except Exception:
            auto_restart = True

        restart_runs = []
        skipped_runs = []

        for run_num in restart_needed_runs:
            run_name = f'run{run_num:03}'
            run_dir = os.path.join(spinup_work_dir, run_name)

            if not os.path.exists(run_dir):
                skipped_runs.append((run_num, "Run directory not found"))
                continue

            # Check restart_timestamp exists
            restart_timestamp_file = os.path.join(run_dir, 'restart_timestamp')
            if not os.path.exists(restart_timestamp_file):
                skipped_runs.append(
                    (run_num, "No restart_timestamp (run may have failed)"))
                continue

            # Check not already completed
            try:
                with open(restart_timestamp_file, 'r') as f:
                    current_time = f.read().strip()
                namelist = compass.namelist.ingest(
                    os.path.join(run_dir, 'namelist.landice'))
                stop_time = (namelist['time_management']['config_stop_time']
                             .strip().strip("'"))
                if current_time == stop_time:
                    skipped_runs.append((run_num, "Already completed"))
                    continue
            except Exception as e:
                skipped_runs.append(
                    (run_num, f"Error reading completion status: {e}"))
                continue

            # Check max restart attempts
            restart_dirs = [d for d in os.listdir(run_dir)
                            if d.startswith('restart_attempt_')]
            if len(restart_dirs) >= max_consecutive_restarts:
                skipped_runs.append(
                    (run_num,
                     f"Max restart attempts reached "
                     f"({len(restart_dirs)}/{max_consecutive_restarts})"))
                continue

            if not auto_restart:
                skipped_runs.append((run_num, "Auto-restart disabled"))
                continue

            restart_runs.append(run_num)
            print(f"Scheduling restart for {run_name}")
            self.add_step(InPlaceRestartMember(
                test_case=self,
                run_num=run_num,
                spinup_work_dir=spinup_work_dir
            ))

        if skipped_runs:
            print("\nSkipped runs:")
            for run_num, reason in skipped_runs:
                print(f"  run{run_num:03}: {reason}")

        self.restart_run_numbers = restart_runs
        self.steps_to_run = ['ensemble_manager']

    # no run() method is needed
    # no validate() method is needed
