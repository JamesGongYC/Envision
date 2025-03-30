# Envision Outputs

This directory stores outputs from GCAM model runs and subsequent analyses.

## Structure

- **scenarios/**: Raw outputs from GCAM scenario runs
  - Contains CSV files with model outputs organized by scenario
  - Includes a unified dataset for analysis (`unified_results.csv`)

- **topology/**: Results from topological data analysis
  - Persistence diagrams showing stable features across parameter spaces
  - Mapper graphs visualizing the shape of the solution space
  - Metrics quantifying topological features

- **analysis/**: Processed analysis results
  - Scenario clusters identified through topological analysis
  - Critical thresholds where system behavior changes
  - Robustness metrics for different policy options
  - Visualizations of key findings

## Data Format

### Scenario Results

The `scenarios/unified_results.csv` file contains:
- Parameter values for each scenario
- Key output metrics from GCAM
- Scenario identifiers and metadata

### Topology Results

Persistent homology results include:
- Birth and death times of topological features
- Betti numbers across dimensions
- Persistence landscapes and silhouettes

Mapper outputs include:
- Graph structures capturing the shape of the data
- Node metadata linking back to original scenarios
- Network metrics characterizing the topology

## Usage Notes

- Results are organized to facilitate both individual scenario analysis and cross-scenario comparison
- Topological features are stored with references back to generating parameters
- The directory structure supports the iterative workflow described in the research proposal 