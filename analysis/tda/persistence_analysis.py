#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Persistence Homology Analysis for GCAM Outputs

This module implements topological data analysis methods for analyzing
high-dimensional outputs from GCAM scenario runs.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
import gudhi as gd
from gudhi.representations import Landscape

class PersistenceAnalyzer:
    """Class for analyzing GCAM outputs using persistence homology."""
    
    def __init__(self, output_path):
        """
        Initialize the analyzer.
        
        Parameters:
        -----------
        output_path : str
            Path to GCAM output files
        """
        self.output_path = output_path
        self.data = None
        self.persistence_diagrams = {}
        
    def load_data(self, filename):
        """
        Load data from GCAM output CSV.
        
        Parameters:
        -----------
        filename : str
            Name of the CSV file to load
            
        Returns:
        --------
        pandas.DataFrame
            Loaded data
        """
        self.data = pd.read_csv(f"{self.output_path}/{filename}")
        return self.data
        
    def compute_persistence(self, data_columns, max_dimension=2, max_edge_length=float('inf')):
        """
        Compute persistence diagrams from data columns.
        
        Parameters:
        -----------
        data_columns : list
            List of column names to use for computation
        max_dimension : int
            Maximum homology dimension to compute
        max_edge_length : float
            Maximum length of edges in the Vietoris-Rips complex
            
        Returns:
        --------
        dict
            Dictionary of persistence diagrams by dimension
        """
        if self.data is None:
            raise ValueError("No data loaded. Call load_data first.")
            
        # Extract and normalize data
        data_matrix = self.data[data_columns].values
        scaler = StandardScaler()
        normalized_data = scaler.fit_transform(data_matrix)
        
        # Compute persistence diagrams using Vietoris-Rips complex
        rips_complex = gd.RipsComplex(points=normalized_data, max_edge_length=max_edge_length)
        simplex_tree = rips_complex.create_simplex_tree(max_dimension=max_dimension)
        
        # Compute persistence
        simplex_tree.compute_persistence()
        
        # Store results by dimension
        self.persistence_diagrams = {}
        for dim in range(max_dimension + 1):
            self.persistence_diagrams[dim] = simplex_tree.persistence_intervals_in_dimension(dim)
            
        return self.persistence_diagrams
        
    def plot_persistence_diagram(self, dimension=1, save_path=None):
        """
        Plot persistence diagram for a specific dimension.
        
        Parameters:
        -----------
        dimension : int
            Homology dimension to plot
        save_path : str, optional
            Path to save the plot, if None will display instead
        """
        if not self.persistence_diagrams:
            raise ValueError("No persistence diagrams computed. Call compute_persistence first.")
            
        if dimension not in self.persistence_diagrams:
            raise ValueError(f"No persistence diagram for dimension {dimension}")
            
        plt.figure(figsize=(8, 8))
        plt.scatter(
            self.persistence_diagrams[dimension][:, 0],
            self.persistence_diagrams[dimension][:, 1],
            s=10, alpha=0.6
        )
        
        # Get plot boundaries
        max_val = np.max(self.persistence_diagrams[dimension]) if len(self.persistence_diagrams[dimension]) > 0 else 1
        min_val = np.min(self.persistence_diagrams[dimension]) if len(self.persistence_diagrams[dimension]) > 0 else 0
        
        # Add diagonal
        diag_min = min_val - 0.05 * (max_val - min_val)
        diag_max = max_val + 0.05 * (max_val - min_val)
        plt.plot([diag_min, diag_max], [diag_min, diag_max], 'k--')
        
        plt.title(f"Persistence Diagram (H{dimension})")
        plt.xlabel("Birth")
        plt.ylabel("Death")
        plt.axis('equal')
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path)
        else:
            plt.show()

if __name__ == "__main__":
    # Example usage
    analyzer = PersistenceAnalyzer("../../outputs/scenarios")
    # analyzer.load_data("scenario_results.csv")
    # analyzer.compute_persistence(["temperature", "emissions", "gdp"])
    # analyzer.plot_persistence_diagram(dimension=1) 