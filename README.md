# Envision

Navigating Complexity: Enhancing Climate Policy Decision-Making Through Topological Analysis of Multi-Sector Systems

## Overview

Envision is a framework for parameter sampling and topological analysis of climate model outputs. It extends the Global Change Analysis Model (GCAM) with capabilities for exploratory modeling and advanced data analysis to support robust decision-making under deep uncertainty.

## Key Components

- **Parameter Sampling**: Python-based framework for efficient parameter space exploration
  - Multiple sampling strategies (Latin Hypercube, Sobol, etc.)
  - Visualization of parameter distributions
  - Integration with GCAM's batch mode

- **Topological Data Analysis**: Tools for extracting meaningful structures from high-dimensional model outputs
  - Persistence homology analysis
  - Mapper algorithm visualization
  - Network analysis of topological structures

- **Interpretation Framework**: Methods for translating mathematical structures into policy-relevant insights

## Project Structure

- `gcam-core/`: The core GCAM model
- `analysis/`: Analysis tools
  - `sampling/`: Parameter sampling framework
  - `tda/`: Topological data analysis
  - `visualization/`: Visualization tools
  - `interpretation/`: AI-based interpretation
- `outputs/`: Storage for model outputs and analysis results
  - `scenarios/`: Raw model outputs
  - `topology/`: Topological analysis results
  - `analysis/`: Processed insights

## Getting Started

### Prerequisites

- Python 3.8+
- GCAM 5.3+
- Required Python packages: `numpy`, `pandas`, `pyDOE2`, `sobol_seq`, `gudhi`, `kmapper`, `networkx`

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/JamesGongYC/Envision.git
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up GCAM according to its documentation

### Parameter Sampling

Run a sampling workflow:
```bash
python analysis/sampling/run_sampling_workflow.py --method lhs --samples 50 --gcam-root path/to/gcam-core
```

### Analyzing Results

Convert GCAM outputs to TDA format:
```bash
python analysis/gcam_to_tda.py --output-dir outputs/scenarios --batch-file parameter_sampling_batch.xml 
```

Run topological analysis:
```bash
# See analysis/README.md for details
```

## License

This project is open source under [LICENSE]. 