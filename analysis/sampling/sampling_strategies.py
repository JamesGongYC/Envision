#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Parameter Sampling Strategies for GCAM

This module implements various sampling strategies for parameter space exploration
with GCAM, providing a more flexible and extensible approach than the C++ implementation.
"""

import numpy as np
import pandas as pd
from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Optional, Union
from pyDOE2 import lhs  # Latin Hypercube Sampling
import sobol_seq  # Sobol sequence
import matplotlib.pyplot as plt
from scipy.stats import qmc


class SamplingStrategy(ABC):
    """Abstract base class for parameter sampling strategies."""
    
    def __init__(self, name: str):
        """
        Initialize the sampling strategy.
        
        Parameters:
        -----------
        name : str
            Name of the sampling strategy
        """
        self.name = name
    
    @abstractmethod
    def generate_samples(self, lower_bounds: List[float], upper_bounds: List[float], 
                         num_samples: int) -> np.ndarray:
        """
        Generate sample points in the parameter space.
        
        Parameters:
        -----------
        lower_bounds : List[float]
            Lower bounds for each parameter
        upper_bounds : List[float]
            Upper bounds for each parameter
        num_samples : int
            Number of samples to generate
            
        Returns:
        --------
        np.ndarray
            Array of sample points, shape (num_samples, num_dimensions)
        """
        pass
    
    def visualize_samples(self, samples: np.ndarray, parameter_names: List[str] = None,
                          save_path: Optional[str] = None):
        """
        Visualize the generated samples.
        
        Parameters:
        -----------
        samples : np.ndarray
            Sample points to visualize
        parameter_names : List[str], optional
            Names of the parameters for labeling
        save_path : str, optional
            Path to save the visualization, if None will display instead
        """
        num_dimensions = samples.shape[1]
        
        if num_dimensions <= 1:
            raise ValueError("Cannot visualize samples with less than 2 dimensions")
        
        if parameter_names is None:
            parameter_names = [f"Param {i+1}" for i in range(num_dimensions)]
        
        if num_dimensions == 2:
            # 2D scatterplot
            plt.figure(figsize=(8, 8))
            plt.scatter(samples[:, 0], samples[:, 1], s=20, alpha=0.6)
            plt.xlabel(parameter_names[0])
            plt.ylabel(parameter_names[1])
            plt.title(f"{self.name} - 2D Projection")
            plt.grid(True, alpha=0.3)
            
        else:
            # Pairwise scatter plots for higher dimensions
            fig, axes = plt.subplots(num_dimensions, num_dimensions, 
                                    figsize=(3*num_dimensions, 3*num_dimensions))
            fig.suptitle(f"{self.name} - Pairwise Projections", fontsize=16)
            
            for i in range(num_dimensions):
                for j in range(num_dimensions):
                    if i == j:
                        # Histogram on diagonal
                        axes[i, j].hist(samples[:, i], bins=15, alpha=0.7)
                        axes[i, j].set_title(parameter_names[i])
                    else:
                        # Scatter plot off diagonal
                        axes[i, j].scatter(samples[:, j], samples[:, i], s=5, alpha=0.6)
                        if i == num_dimensions - 1:
                            axes[i, j].set_xlabel(parameter_names[j])
                        if j == 0:
                            axes[i, j].set_ylabel(parameter_names[i])
            
            plt.tight_layout(rect=[0, 0, 1, 0.97])
        
        if save_path:
            plt.savefig(save_path)
        else:
            plt.show()


class LatinHypercubeSampling(SamplingStrategy):
    """Latin Hypercube Sampling implementation."""
    
    def __init__(self, criterion: str = "maximin"):
        """
        Initialize Latin Hypercube Sampling.
        
        Parameters:
        -----------
        criterion : str
            Optimization criterion, options: 'center', 'maximin', 'correlation', 'c'
        """
        super().__init__("Latin Hypercube Sampling")
        self.criterion = criterion
    
    def generate_samples(self, lower_bounds: List[float], upper_bounds: List[float], 
                         num_samples: int) -> np.ndarray:
        """
        Generate sample points using Latin Hypercube Sampling.
        
        Parameters:
        -----------
        lower_bounds : List[float]
            Lower bounds for each parameter
        upper_bounds : List[float]
            Upper bounds for each parameter
        num_samples : int
            Number of samples to generate
            
        Returns:
        --------
        np.ndarray
            Array of sample points, shape (num_samples, num_dimensions)
        """
        num_dimensions = len(lower_bounds)
        
        # Generate LHS samples in [0, 1]
        lhs_samples = lhs(num_dimensions, samples=num_samples, criterion=self.criterion)
        
        # Scale samples to the parameter ranges
        lower_bounds = np.array(lower_bounds)
        upper_bounds = np.array(upper_bounds)
        
        ranges = upper_bounds - lower_bounds
        scaled_samples = lower_bounds + lhs_samples * ranges
        
        return scaled_samples


class SobolSampling(SamplingStrategy):
    """Sobol sequence sampling implementation."""
    
    def __init__(self):
        """Initialize Sobol sequence sampling."""
        super().__init__("Sobol Sequence Sampling")
    
    def generate_samples(self, lower_bounds: List[float], upper_bounds: List[float], 
                         num_samples: int) -> np.ndarray:
        """
        Generate sample points using Sobol sequence.
        
        Parameters:
        -----------
        lower_bounds : List[float]
            Lower bounds for each parameter
        upper_bounds : List[float]
            Upper bounds for each parameter
        num_samples : int
            Number of samples to generate
            
        Returns:
        --------
        np.ndarray
            Array of sample points, shape (num_samples, num_dimensions)
        """
        num_dimensions = len(lower_bounds)
        
        # Skip the first point (0, 0, ..., 0)
        sobol_samples = sobol_seq.i4_sobol_generate(num_dimensions, num_samples + 1)[1:]
        
        # Scale samples to the parameter ranges
        lower_bounds = np.array(lower_bounds)
        upper_bounds = np.array(upper_bounds)
        
        ranges = upper_bounds - lower_bounds
        scaled_samples = lower_bounds + sobol_samples * ranges
        
        return scaled_samples


class RandomSampling(SamplingStrategy):
    """Random sampling implementation."""
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize random sampling.
        
        Parameters:
        -----------
        seed : int, optional
            Random seed for reproducibility
        """
        super().__init__("Random Sampling")
        self.seed = seed
        if seed is not None:
            np.random.seed(seed)
    
    def generate_samples(self, lower_bounds: List[float], upper_bounds: List[float], 
                         num_samples: int) -> np.ndarray:
        """
        Generate sample points using random sampling.
        
        Parameters:
        -----------
        lower_bounds : List[float]
            Lower bounds for each parameter
        upper_bounds : List[float]
            Upper bounds for each parameter
        num_samples : int
            Number of samples to generate
            
        Returns:
        --------
        np.ndarray
            Array of sample points, shape (num_samples, num_dimensions)
        """
        num_dimensions = len(lower_bounds)
        
        # Generate random samples in [0, 1]
        random_samples = np.random.random((num_samples, num_dimensions))
        
        # Scale samples to the parameter ranges
        lower_bounds = np.array(lower_bounds)
        upper_bounds = np.array(upper_bounds)
        
        ranges = upper_bounds - lower_bounds
        scaled_samples = lower_bounds + random_samples * ranges
        
        return scaled_samples


class HaltonSampling(SamplingStrategy):
    """Halton sequence sampling implementation."""
    
    def __init__(self):
        """Initialize Halton sequence sampling."""
        super().__init__("Halton Sequence Sampling")
    
    def generate_samples(self, lower_bounds: List[float], upper_bounds: List[float], 
                         num_samples: int) -> np.ndarray:
        """
        Generate sample points using Halton sequence.
        
        Parameters:
        -----------
        lower_bounds : List[float]
            Lower bounds for each parameter
        upper_bounds : List[float]
            Upper bounds for each parameter
        num_samples : int
            Number of samples to generate
            
        Returns:
        --------
        np.ndarray
            Array of sample points, shape (num_samples, num_dimensions)
        """
        num_dimensions = len(lower_bounds)
        
        # Use scipy's qmc for Halton sequence
        sampler = qmc.Halton(d=num_dimensions, scramble=True)
        halton_samples = sampler.random(n=num_samples)
        
        # Scale samples to the parameter ranges
        lower_bounds = np.array(lower_bounds)
        upper_bounds = np.array(upper_bounds)
        
        ranges = upper_bounds - lower_bounds
        scaled_samples = lower_bounds + halton_samples * ranges
        
        return scaled_samples


class OrthogonalSampling(SamplingStrategy):
    """Orthogonal sampling implementation."""
    
    def __init__(self):
        """Initialize orthogonal sampling."""
        super().__init__("Orthogonal Sampling")
    
    def generate_samples(self, lower_bounds: List[float], upper_bounds: List[float], 
                         num_samples: int) -> np.ndarray:
        """
        Generate sample points using orthogonal sampling.
        
        Parameters:
        -----------
        lower_bounds : List[float]
            Lower bounds for each parameter
        upper_bounds : List[float]
            Upper bounds for each parameter
        num_samples : int
            Number of samples to generate
            
        Returns:
        --------
        np.ndarray
            Array of sample points, shape (num_samples, num_dimensions)
        """
        # Use pyDOE2's orthogonal Latin Hypercube design
        ortho_samples = lhs(len(lower_bounds), samples=num_samples, criterion='correlation')
        
        # Scale samples to the parameter ranges
        lower_bounds = np.array(lower_bounds)
        upper_bounds = np.array(upper_bounds)
        
        ranges = upper_bounds - lower_bounds
        scaled_samples = lower_bounds + ortho_samples * ranges
        
        return scaled_samples


if __name__ == "__main__":
    # Example usage
    lower_bounds = [0.0, 0.0, 0.0]
    upper_bounds = [1.0, 1.0, 1.0]
    num_samples = 100
    
    # Compare different sampling methods
    lhs_sampler = LatinHypercubeSampling()
    sobol_sampler = SobolSampling()
    random_sampler = RandomSampling(seed=42)
    
    lhs_samples = lhs_sampler.generate_samples(lower_bounds, upper_bounds, num_samples)
    sobol_samples = sobol_sampler.generate_samples(lower_bounds, upper_bounds, num_samples)
    random_samples = random_sampler.generate_samples(lower_bounds, upper_bounds, num_samples)
    
    # Visualize first 2 dimensions
    param_names = ["Param 1", "Param 2", "Param 3"]
    
    lhs_sampler.visualize_samples(lhs_samples, param_names)
    sobol_sampler.visualize_samples(sobol_samples, param_names)
    random_sampler.visualize_samples(random_samples, param_names) 