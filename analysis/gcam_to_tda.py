#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
GCAM Output Converter for Topological Data Analysis

This script converts GCAM batch outputs to a format suitable for
topological data analysis by extracting key metrics and creating
a unified dataset.
"""

import os
import pandas as pd
import numpy as np
import glob
import argparse
import xml.etree.ElementTree as ET
import re

def parse_gcam_query_csv(filepath):
    """
    Parse a GCAM query CSV file.
    
    Parameters:
    -----------
    filepath : str
        Path to the CSV file
        
    Returns:
    --------
    pandas.DataFrame
        Parsed data with scenario name extracted
    """
    # Extract scenario name from filepath
    scenario_name = os.path.basename(os.path.dirname(filepath))
    
    # Read the CSV file
    df = pd.read_csv(filepath)
    
    # Add scenario name column
    df['scenario'] = scenario_name
    
    return df

def extract_parameter_values(batch_xml_file, scenario_name):
    """
    Extract parameter values from batch XML file for a specific scenario.
    
    Parameters:
    -----------
    batch_xml_file : str
        Path to the batch XML file
    scenario_name : str
        Name of the scenario to extract parameters for
        
    Returns:
    --------
    dict
        Dictionary of parameter values
    """
    tree = ET.parse(batch_xml_file)
    root = tree.getroot()
    
    # Find the scenario by name
    params = {}
    for component_set in root.findall(".//ComponentSet"):
        for file_set in component_set.findall(".//FileSet"):
            if file_set.get('name') in scenario_name:
                for value in file_set.findall(".//Value"):
                    param_name = value.get('name')
                    param_file = value.text
                    params[param_name] = param_file
                    
    return params

def create_unified_dataset(gcam_output_dir, batch_xml_file, query_names, output_file):
    """
    Create a unified dataset from GCAM batch outputs.
    
    Parameters:
    -----------
    gcam_output_dir : str
        Directory containing GCAM output files
    batch_xml_file : str
        Path to the batch XML file
    query_names : list
        List of query names to extract data from
    output_file : str
        Path to save the unified dataset
        
    Returns:
    --------
    pandas.DataFrame
        Unified dataset with parameters and outputs
    """
    # Find all scenario directories
    scenario_dirs = [d for d in os.listdir(gcam_output_dir) 
                    if os.path.isdir(os.path.join(gcam_output_dir, d))]
    
    # Initialize results dataframe
    results = []
    
    for scenario in scenario_dirs:
        scenario_data = {'scenario': scenario}
        
        # Extract parameter values
        params = extract_parameter_values(batch_xml_file, scenario)
        scenario_data.update(params)
        
        # Extract query results
        for query in query_names:
            query_pattern = os.path.join(gcam_output_dir, scenario, f"*{query}*.csv")
            query_files = glob.glob(query_pattern)
            
            if query_files:
                query_df = parse_gcam_query_csv(query_files[0])
                
                # Extract key metrics based on query type
                if 'temperature' in query.lower():
                    # Get global mean temperature for final year
                    final_year = query_df['year'].max()
                    temp = query_df[query_df['year'] == final_year]['value'].mean()
                    scenario_data['temperature_final'] = temp
                
                elif 'emissions' in query.lower():
                    # Get cumulative emissions
                    scenario_data['emissions_cumulative'] = query_df['value'].sum()
                    
                    # Get emissions in 2050 and 2100 (or nearest available)
                    years_of_interest = [2050, 2100]
                    for year in years_of_interest:
                        nearest_year = query_df['year'].iloc[(query_df['year'] - year).abs().argsort()[0]]
                        value = query_df[query_df['year'] == nearest_year]['value'].mean()
                        scenario_data[f'emissions_{nearest_year}'] = value
                
                elif 'gdp' in query.lower() or 'economic' in query.lower():
                    # Get global GDP for final year
                    final_year = query_df['year'].max()
                    gdp = query_df[query_df['year'] == final_year]['value'].sum()
                    scenario_data['gdp_final'] = gdp
                    
                    # Calculate GDP growth rate
                    if len(query_df['year'].unique()) > 1:
                        # Sort by year and calculate compound annual growth rate
                        years = sorted(query_df['year'].unique())
                        initial_gdp = query_df[query_df['year'] == years[0]]['value'].sum()
                        final_gdp = query_df[query_df['year'] == years[-1]]['value'].sum()
                        years_diff = years[-1] - years[0]
                        if initial_gdp > 0:
                            growth_rate = (final_gdp / initial_gdp) ** (1 / years_diff) - 1
                            scenario_data['gdp_growth_rate'] = growth_rate
                
                elif 'energy' in query.lower():
                    # Extract energy mix percentages for final year
                    final_year = query_df['year'].max()
                    energy_mix = query_df[query_df['year'] == final_year]
                    
                    if 'technology' in query_df.columns:
                        for tech in ['coal', 'gas', 'oil', 'nuclear', 'hydro', 'wind', 'solar', 'biomass']:
                            tech_data = energy_mix[energy_mix['technology'].str.contains(tech, case=False, na=False)]
                            if not tech_data.empty:
                                scenario_data[f'energy_{tech}_share'] = tech_data['value'].sum() / energy_mix['value'].sum()
        
        results.append(scenario_data)
    
    # Convert to DataFrame
    results_df = pd.DataFrame(results)
    
    # Save to file
    results_df.to_csv(output_file, index=False)
    
    return results_df

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Convert GCAM outputs to TDA format')
    parser.add_argument('--output-dir', type=str, required=True, 
                        help='Directory containing GCAM output files')
    parser.add_argument('--batch-file', type=str, required=True,
                        help='Path to the batch XML file')
    parser.add_argument('--query-names', type=str, nargs='+', required=True,
                        help='List of query names to extract data from')
    parser.add_argument('--output-file', type=str, default='../outputs/scenarios/unified_results.csv',
                        help='Path to save the unified dataset')
    
    args = parser.parse_args()
    
    create_unified_dataset(args.output_dir, args.batch_file, args.query_names, args.output_file) 