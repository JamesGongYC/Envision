#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
GCAM Parameter Sampling Workflow

This script orchestrates the complete workflow for parameter sampling with GCAM:
1. Define parameter space
2. Generate sample points
3. Create parameter files
4. Create batch file
5. Run GCAM
6. Process outputs

Usage:
    python run_sampling_workflow.py --method lhs --samples 50 --gcam-root ../gcam-core
"""

import os
import sys
import argparse
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Any

# Import local modules
from sampling_strategies import (
    SamplingStrategy, 
    LatinHypercubeSampling, 
    SobolSampling, 
    RandomSampling,
    HaltonSampling,
    OrthogonalSampling
)
from parameter_space import Parameter, ParameterSpace, GCAMParameterManager


def setup_logging(log_file: str = None, level: int = logging.INFO) -> logging.Logger:
    """
    Set up logging configuration.
    
    Parameters:
    -----------
    log_file : str, optional
        Path to log file, if None logging to file is disabled
    level : int, optional
        Logging level
        
    Returns:
    --------
    logging.Logger
        Logger instance
    """
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Add file handler if log file is specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_sampler(method: str) -> SamplingStrategy:
    """
    Get a sampler instance based on the specified method.
    
    Parameters:
    -----------
    method : str
        Sampling method name
        
    Returns:
    --------
    SamplingStrategy
        Sampler instance
        
    Raises:
    -------
    ValueError
        If the specified method is not supported
    """
    method = method.lower()
    
    if method == "lhs":
        return LatinHypercubeSampling()
    elif method == "sobol":
        return SobolSampling()
    elif method == "random":
        return RandomSampling()
    elif method == "halton":
        return HaltonSampling()
    elif method == "orthogonal":
        return OrthogonalSampling()
    else:
        raise ValueError(f"Unsupported sampling method: {method}")


def create_custom_parameter_space(config_file: str = None) -> Dict[str, Parameter]:
    """
    Create a custom parameter space based on configuration.
    
    Parameters:
    -----------
    config_file : str, optional
        Path to parameter configuration file
        
    Returns:
    --------
    Dict[str, Parameter]
        Dictionary of parameters
    """
    parameters = {}
    
    if config_file and os.path.exists(config_file):
        # Load parameters from configuration file
        try:
            config_df = pd.read_csv(config_file)
            
            for _, row in config_df.iterrows():
                param = Parameter(
                    name=row['name'],
                    lower_bound=float(row['lower_bound']),
                    upper_bound=float(row['upper_bound']),
                    units=row.get('units', ''),
                    description=row.get('description', ''),
                    xml_path=row.get('xml_path', ''),
                    default_value=float(row['default_value']) if 'default_value' in row else None
                )
                parameters[param.name] = param
                
        except Exception as e:
            logging.error(f"Error loading parameter configuration: {e}")
    
    return parameters


def main():
    """Main function to run the workflow."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="GCAM Parameter Sampling Workflow")
    parser.add_argument("--method", type=str, default="lhs", 
                        choices=["lhs", "sobol", "random", "halton", "orthogonal"],
                        help="Sampling method to use")
    parser.add_argument("--samples", type=int, default=10,
                        help="Number of samples to generate")
    parser.add_argument("--gcam-root", type=str, required=True,
                        help="Path to GCAM root directory")
    parser.add_argument("--output-dir", type=str, default="outputs",
                        help="Directory to store outputs")
    parser.add_argument("--config-file", type=str, default=None,
                        help="Path to parameter configuration file")
    parser.add_argument("--log-file", type=str, default=None,
                        help="Path to log file")
    parser.add_argument("--run-gcam", action="store_true",
                        help="Run GCAM after generating parameter files")
    parser.add_argument("--gcam-config", type=str, default=None,
                        help="Path to GCAM configuration file")
    parser.add_argument("--analyze", action="store_true",
                        help="Analyze results after running")
    
    args = parser.parse_args()
    
    # Set up logging
    logger = setup_logging(args.log_file)
    logger.info(f"Starting GCAM Parameter Sampling Workflow with method: {args.method}, samples: {args.samples}")
    
    # Create output directories
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, "parameters"), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, "plots"), exist_ok=True)
    
    # Initialize GCAM parameter manager
    gcam_manager = GCAMParameterManager(args.gcam_root, args.output_dir)
    
    # Define parameters
    if args.config_file:
        # Load parameters from configuration file
        custom_params = create_custom_parameter_space(args.config_file)
        for param in custom_params.values():
            gcam_manager.add_parameter(param)
    else:
        # Use standard parameters
        gcam_manager.define_standard_parameters()
    
    # Get parameter space details
    param_names = gcam_manager.parameter_space.get_parameter_names()
    lower_bounds = gcam_manager.parameter_space.get_lower_bounds()
    upper_bounds = gcam_manager.parameter_space.get_upper_bounds()
    
    logger.info(f"Parameter space defined with {len(param_names)} parameters: {param_names}")
    
    # Create sampler and generate samples
    sampler = get_sampler(args.method)
    logger.info(f"Using {sampler.name} to generate {args.samples} samples")
    
    samples = sampler.generate_samples(lower_bounds, upper_bounds, args.samples)
    
    # Visualize samples
    plot_path = os.path.join(args.output_dir, "plots", f"{args.method}_samples.png")
    logger.info(f"Saving sample visualization to {plot_path}")
    sampler.visualize_samples(samples, param_names, save_path=plot_path)
    
    # Create scenarios from samples
    logger.info("Creating scenario files from samples")
    scenarios = gcam_manager.create_scenarios_from_samples(sampler.name, samples, param_names)
    
    # Save sample values to CSV
    sample_df = pd.DataFrame(samples, columns=param_names)
    sample_df['scenario'] = [s['name'] for s in scenarios]
    sample_csv_path = os.path.join(args.output_dir, "parameter_samples.csv")
    sample_df.to_csv(sample_csv_path, index=False)
    logger.info(f"Saved parameter samples to {sample_csv_path}")
    
    # Create batch file
    scenario_set = {
        "name": f"{args.method}_analysis",
        "scenarios": scenarios
    }
    
    batch_file = gcam_manager.create_batch_file([scenario_set])
    logger.info(f"Created batch file: {batch_file}")
    
    # Run GCAM if requested
    if args.run_gcam:
        if args.gcam_config:
            logger.info(f"Running GCAM with configuration: {args.gcam_config}")
            success = gcam_manager.run_gcam(args.gcam_config, batch_file)
            
            if success:
                logger.info("GCAM run completed successfully")
            else:
                logger.error("GCAM run failed")
        else:
            logger.error("GCAM configuration file not specified, skipping GCAM run")
    
    # Analyze results if requested
    if args.analyze:
        logger.info("Analyzing results")
        # TODO: Implement result analysis
        # This would be integrated with the TDA tools
    
    logger.info("Workflow completed successfully")


if __name__ == "__main__":
    main() 