#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Parameter Space Manager for GCAM

This module provides classes for defining parameter spaces and integrating
with GCAM for scenario generation.
"""

import os
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from typing import List, Dict, Tuple, Optional, Union, Any
import subprocess
import logging


class Parameter:
    """Class representing a model parameter for sampling."""
    
    def __init__(self, name: str, lower_bound: float, upper_bound: float, 
                 units: str = "", description: str = "", xml_path: str = "",
                 default_value: Optional[float] = None):
        """
        Initialize a parameter.
        
        Parameters:
        -----------
        name : str
            Name of the parameter
        lower_bound : float
            Lower bound for sampling
        upper_bound : float
            Upper bound for sampling
        units : str, optional
            Units of the parameter
        description : str, optional
            Description of the parameter
        xml_path : str, optional
            Path in XML where this parameter should be inserted
        default_value : float, optional
            Default value of the parameter
        """
        self.name = name
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.units = units
        self.description = description
        self.xml_path = xml_path
        self.default_value = default_value if default_value is not None else (lower_bound + upper_bound) / 2
        
    def __repr__(self) -> str:
        """String representation of the parameter."""
        return f"Parameter({self.name}, range=[{self.lower_bound}, {self.upper_bound}] {self.units})"


class ParameterSpace:
    """Class for managing a space of parameters to sample."""
    
    def __init__(self):
        """Initialize an empty parameter space."""
        self.parameters: Dict[str, Parameter] = {}
        self.logger = logging.getLogger(__name__)
        
    def add_parameter(self, parameter: Parameter) -> None:
        """
        Add a parameter to the space.
        
        Parameters:
        -----------
        parameter : Parameter
            Parameter to add
        """
        self.parameters[parameter.name] = parameter
        
    def get_parameter(self, name: str) -> Parameter:
        """
        Get a parameter by name.
        
        Parameters:
        -----------
        name : str
            Name of the parameter
            
        Returns:
        --------
        Parameter
            The requested parameter
            
        Raises:
        -------
        KeyError
            If parameter with given name doesn't exist
        """
        if name not in self.parameters:
            raise KeyError(f"Parameter '{name}' not found in parameter space")
        return self.parameters[name]
    
    def get_parameter_names(self) -> List[str]:
        """
        Get all parameter names.
        
        Returns:
        --------
        List[str]
            List of parameter names
        """
        return list(self.parameters.keys())
    
    def get_lower_bounds(self) -> List[float]:
        """
        Get lower bounds for all parameters.
        
        Returns:
        --------
        List[float]
            List of lower bounds in the order of parameter names
        """
        return [param.lower_bound for param in self.parameters.values()]
    
    def get_upper_bounds(self) -> List[float]:
        """
        Get upper bounds for all parameters.
        
        Returns:
        --------
        List[float]
            List of upper bounds in the order of parameter names
        """
        return [param.upper_bound for param in self.parameters.values()]
    
    def size(self) -> int:
        """
        Get the number of parameters in the space.
        
        Returns:
        --------
        int
            Number of parameters
        """
        return len(self.parameters)


class GCAMParameterManager:
    """Class for managing GCAM parameters and creating batch files."""
    
    def __init__(self, gcam_root: str, output_dir: str = "outputs"):
        """
        Initialize the GCAM parameter manager.
        
        Parameters:
        -----------
        gcam_root : str
            Path to GCAM root directory
        output_dir : str, optional
            Directory to store output files
        """
        self.gcam_root = gcam_root
        self.output_dir = output_dir
        self.parameter_space = ParameterSpace()
        self.logger = logging.getLogger(__name__)
        
    def define_standard_parameters(self) -> None:
        """Define a set of standard parameters commonly used in research."""
        # Climate parameters
        self.parameter_space.add_parameter(Parameter(
            name="climate-sensitivity",
            lower_bound=2.0,
            upper_bound=4.5,
            units="°C",
            description="Equilibrium climate sensitivity",
            xml_path="climate/magicc-input/climate_sensitivity"
        ))
        
        self.parameter_space.add_parameter(Parameter(
            name="ocean-carbon-flux",
            lower_bound=1.5,
            upper_bound=3.5,
            units="GtC/yr",
            description="1980s Ocean Carbon Flux",
            xml_path="climate/magicc-input/ocean_carbon_flux"
        ))
        
        # Economic parameters
        self.parameter_space.add_parameter(Parameter(
            name="social-discount-rate",
            lower_bound=0.01,
            upper_bound=0.05,
            units="fraction",
            description="Social discount rate",
            xml_path="socioeconomics/social_discount_rate"
        ))
        
        self.parameter_space.add_parameter(Parameter(
            name="interest-rate",
            lower_bound=0.05,
            upper_bound=0.10,
            units="fraction",
            description="Investment interest rate",
            xml_path="socioeconomics/interest_rate"
        ))
        
        # Technology parameters
        self.parameter_space.add_parameter(Parameter(
            name="renewables-cost-improvement",
            lower_bound=0.005,
            upper_bound=0.025,
            units="fraction/yr",
            description="Annual cost improvement rate for renewable technologies",
            xml_path="technology/renewables/cost_improvement_rate"
        ))
        
        self.parameter_space.add_parameter(Parameter(
            name="ccs-efficiency",
            lower_bound=0.85,
            upper_bound=0.95,
            units="fraction",
            description="Carbon capture and storage efficiency",
            xml_path="technology/ccs/efficiency"
        ))
    
    def add_parameter(self, parameter: Parameter) -> None:
        """
        Add a parameter to the parameter space.
        
        Parameters:
        -----------
        parameter : Parameter
            Parameter to add
        """
        self.parameter_space.add_parameter(parameter)
    
    def create_xml_template(self, parameter: Parameter, value: float) -> str:
        """
        Create an XML file fragment for a parameter value.
        
        Parameters:
        -----------
        parameter : Parameter
            Parameter to create XML for
        value : float
            Value to set for the parameter
            
        Returns:
        --------
        str
            XML fragment as a string
        """
        # Create a simple XML structure
        root = ET.Element("scenario")
        
        # Split the XML path into components
        path_parts = parameter.xml_path.split('/')
        
        # Create nested elements
        current = root
        for part in path_parts[:-1]:
            current = ET.SubElement(current, part)
        
        # Add the value element
        value_elem = ET.SubElement(current, path_parts[-1])
        value_elem.text = str(value)
        
        # Convert to pretty-printed string
        rough_string = ET.tostring(root, 'utf-8')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
    
    def create_parameter_files(self, scenario_name: str, parameter_values: Dict[str, float]) -> List[str]:
        """
        Create XML files for a set of parameter values.
        
        Parameters:
        -----------
        scenario_name : str
            Name of the scenario
        parameter_values : Dict[str, float]
            Dictionary mapping parameter names to values
            
        Returns:
        --------
        List[str]
            List of created file paths
        """
        # Create parameter directory if it doesn't exist
        param_dir = os.path.join(self.output_dir, "parameters", scenario_name)
        os.makedirs(param_dir, exist_ok=True)
        
        created_files = []
        
        # Create XML files for each parameter
        for param_name, value in parameter_values.items():
            parameter = self.parameter_space.get_parameter(param_name)
            xml_content = self.create_xml_template(parameter, value)
            
            # Create file name based on parameter
            file_name = f"{param_name.replace('-', '_')}.xml"
            file_path = os.path.join(param_dir, file_name)
            
            # Write XML to file
            with open(file_path, 'w') as f:
                f.write(xml_content)
            
            created_files.append(file_path)
        
        return created_files
    
    def create_batch_file(self, scenario_sets: List[Dict[str, Any]], 
                         output_file: str = "parameter_sampling_batch.xml") -> str:
        """
        Create a batch file for GCAM with the specified scenarios.
        
        Parameters:
        -----------
        scenario_sets : List[Dict[str, Any]]
            List of scenario sets, each with a name and list of parameter values
        output_file : str, optional
            Path to save the batch file
            
        Returns:
        --------
        str
            Path to the created batch file
        """
        # Create the XML structure
        root = ET.Element("BatchRunner")
        
        # Add each scenario set as a ComponentSet
        for scenario_set in scenario_sets:
            component_set = ET.SubElement(root, "ComponentSet")
            component_set.set("name", scenario_set["name"])
            
            # Add each scenario as a FileSet
            for scenario in scenario_set["scenarios"]:
                file_set = ET.SubElement(component_set, "FileSet")
                file_set.set("name", scenario["name"])
                
                # Add each parameter file as a Value
                for param_name, file_path in scenario["files"].items():
                    value_elem = ET.SubElement(file_set, "Value")
                    value_elem.set("name", param_name)
                    value_elem.text = file_path
        
        # Add runner-set element
        runner_set = ET.SubElement(root, "runner-set")
        ET.SubElement(runner_set, "single-scenario-runner")
        
        # Convert to pretty-printed string
        rough_string = ET.tostring(root, 'utf-8')
        reparsed = minidom.parseString(rough_string)
        xml_str = reparsed.toprettyxml(indent="  ")
        
        # Write to file
        with open(output_file, 'w') as f:
            f.write(xml_str)
        
        return output_file
    
    def create_scenarios_from_samples(self, sampler_name: str, samples: np.ndarray, 
                                    parameter_names: List[str]) -> List[Dict[str, Any]]:
        """
        Convert sample points to scenario definitions.
        
        Parameters:
        -----------
        sampler_name : str
            Name of the sampling method used
        samples : np.ndarray
            Sample points, shape (num_samples, num_dimensions)
        parameter_names : List[str]
            Names of the parameters corresponding to dimensions
            
        Returns:
        --------
        List[Dict[str, Any]]
            List of scenario definitions
        """
        scenarios = []
        
        # Create a scenario for each sample point
        for i, sample in enumerate(samples):
            scenario_name = f"{sampler_name}_scenario_{i+1}"
            
            # Create dictionary of parameter values
            param_values = {parameter_names[j]: sample[j] for j in range(len(parameter_names))}
            
            # Create parameter files
            param_files = self.create_parameter_files(scenario_name, param_values)
            
            # Create dictionary of parameter files
            files_dict = {parameter_names[j]: param_files[j] for j in range(len(parameter_names))}
            
            # Create scenario definition
            scenario = {
                "name": scenario_name,
                "values": param_values,
                "files": files_dict
            }
            
            scenarios.append(scenario)
        
        return scenarios
    
    def run_gcam(self, config_file: str, batch_file: str) -> bool:
        """
        Run GCAM with the specified configuration and batch file.
        
        Parameters:
        -----------
        config_file : str
            Path to GCAM configuration file
        batch_file : str
            Path to batch file
            
        Returns:
        --------
        bool
            True if GCAM ran successfully, False otherwise
        """
        # Set up GCAM command
        gcam_exe = os.path.join(self.gcam_root, "exe", "gcam.exe")
        
        if not os.path.exists(gcam_exe):
            self.logger.error(f"GCAM executable not found at: {gcam_exe}")
            return False
        
        # Set environment variables for GCAM
        env = os.environ.copy()
        env["GCAM_CONFIG_FILE"] = config_file
        env["BATCH_FILE"] = batch_file
        
        try:
            # Run GCAM
            self.logger.info(f"Running GCAM with config: {config_file}, batch: {batch_file}")
            process = subprocess.Popen([gcam_exe], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            
            # Log output
            self.logger.info(f"GCAM stdout: {stdout.decode('utf-8')}")
            if stderr:
                self.logger.warning(f"GCAM stderr: {stderr.decode('utf-8')}")
            
            return process.returncode == 0
        except Exception as e:
            self.logger.error(f"Error running GCAM: {e}")
            return False


if __name__ == "__main__":
    # Example usage
    from sampling_strategies import LatinHypercubeSampling
    
    # Initialize GCAM parameter manager
    gcam_manager = GCAMParameterManager("../gcam-core")
    
    # Define standard parameters
    gcam_manager.define_standard_parameters()
    
    # Get parameter names, lower bounds, and upper bounds
    param_names = gcam_manager.parameter_space.get_parameter_names()
    lower_bounds = gcam_manager.parameter_space.get_lower_bounds()
    upper_bounds = gcam_manager.parameter_space.get_upper_bounds()
    
    # Create sampler and generate samples
    sampler = LatinHypercubeSampling()
    samples = sampler.generate_samples(lower_bounds, upper_bounds, num_samples=5)
    
    # Create scenarios from samples
    scenarios = gcam_manager.create_scenarios_from_samples(sampler.name, samples, param_names)
    
    # Create batch file
    scenario_set = {
        "name": "climate_sensitivity_analysis",
        "scenarios": scenarios
    }
    
    batch_file = gcam_manager.create_batch_file([scenario_set])
    
    print(f"Created batch file: {batch_file}")
    print(f"Created {len(scenarios)} scenarios") 