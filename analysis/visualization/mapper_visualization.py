#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Mapper Visualization for GCAM Outputs

This module implements visualization of Mapper algorithm results
for analyzing high-dimensional outputs from GCAM scenario runs.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import kmapper as km
from sklearn.preprocessing import StandardScaler
from sklearn.manifold import TSNE
import networkx as nx

class MapperVisualizer:
    """Class for visualizing GCAM outputs using the Mapper algorithm."""
    
    def __init__(self, output_path):
        """
        Initialize the visualizer.
        
        Parameters:
        -----------
        output_path : str
            Path to GCAM output files
        """
        self.output_path = output_path
        self.data = None
        self.mapper_result = None
        self.mapper = km.KeplerMapper()
        
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
        
    def compute_mapper(self, data_columns, lens=None, n_cubes=10, overlap=0.5, 
                       clusterer=None, verbose=1):
        """
        Compute Mapper graph from data columns.
        
        Parameters:
        -----------
        data_columns : list
            List of column names to use for computation
        lens : callable or None
            Lens for Mapper, if None uses TSNE
        n_cubes : int
            Number of intervals to split lens values
        overlap : float
            Percentage of overlap between intervals
        clusterer : sklearn.base.ClusterMixin or None
            Clustering algorithm to use, defaults to DBSCAN
        verbose : int
            Verbosity level
            
        Returns:
        --------
        dict
            Mapper graph
        """
        if self.data is None:
            raise ValueError("No data loaded. Call load_data first.")
            
        # Extract and normalize data
        data_matrix = self.data[data_columns].values
        scaler = StandardScaler()
        normalized_data = scaler.fit_transform(data_matrix)
        
        # Create lens if not provided
        if lens is None:
            tsne = TSNE(n_components=2, random_state=42)
            lens_values = tsne.fit_transform(normalized_data)
        else:
            lens_values = lens(normalized_data)
            
        # Compute Mapper graph
        self.mapper_result = self.mapper.map(
            lens_values,
            normalized_data,
            cover=km.Cover(n_cubes=n_cubes, perc_overlap=overlap),
            clusterer=clusterer,
            verbose=verbose
        )
        
        return self.mapper_result
        
    def visualize(self, title="GCAM Scenario Mapper Graph", save_path=None):
        """
        Visualize Mapper graph.
        
        Parameters:
        -----------
        title : str
            Title for the visualization
        save_path : str, optional
            Path to save the visualization, if None will display instead
        """
        if self.mapper_result is None:
            raise ValueError("No Mapper graph computed. Call compute_mapper first.")
            
        # Create visualization
        html = self.mapper.visualize(
            self.mapper_result,
            title=title,
            path_html=save_path if save_path else None
        )
        
        return html
        
    def extract_network(self):
        """
        Extract networkx graph from Mapper result for further analysis.
        
        Returns:
        --------
        networkx.Graph
            Graph representation of Mapper result
        """
        if self.mapper_result is None:
            raise ValueError("No Mapper graph computed. Call compute_mapper first.")
            
        # Create networkx graph
        G = nx.Graph()
        
        # Add nodes with metadata
        for node_id, node_info in self.mapper_result["nodes"].items():
            G.add_node(node_id, size=len(node_info), points=node_info)
            
        # Add edges
        for edge in self.mapper_result["links"]:
            G.add_edge(edge["source"], edge["target"])
            
        return G
        
    def analyze_network(self, G=None):
        """
        Analyze the Mapper network.
        
        Parameters:
        -----------
        G : networkx.Graph or None
            Graph to analyze, if None uses result from extract_network
            
        Returns:
        --------
        dict
            Dictionary of network metrics
        """
        if G is None:
            G = self.extract_network()
            
        metrics = {
            "n_nodes": G.number_of_nodes(),
            "n_edges": G.number_of_edges(),
            "connected_components": nx.number_connected_components(G),
            "avg_degree": sum(dict(G.degree()).values()) / float(G.number_of_nodes()),
            "density": nx.density(G),
            "diameter": max(nx.diameter(C) for C in (G.subgraph(c) for c in nx.connected_components(G)))
        }
        
        return metrics

if __name__ == "__main__":
    # Example usage
    visualizer = MapperVisualizer("../../outputs/scenarios")
    # visualizer.load_data("scenario_results.csv")
    # visualizer.compute_mapper(["temperature", "emissions", "gdp"])
    # visualizer.visualize(save_path="../../outputs/topology/mapper_graph.html")
    # G = visualizer.extract_network()
    # metrics = visualizer.analyze_network(G)
    # print(metrics) 