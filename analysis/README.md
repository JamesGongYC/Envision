# Envision Analysis Framework

This directory contains the tools for analyzing GCAM outputs using topological data analysis (TDA) and visualization techniques.

## Structure

- **sampling/**: Parameter sampling tools for GCAM
  - `sampling_strategies.py`: Implements various sampling methods (LHS, Sobol, etc.)
  - `parameter_space.py`: Parameter space definition and GCAM integration
  - `run_sampling_workflow.py`: End-to-end workflow for parameter sampling
  
- **tda/**: Topological Data Analysis tools
  - `persistence_analysis.py`: Implements persistence homology analysis
  
- **visualization/**: Visualization tools
  - `mapper_visualization.py`: Implements Mapper algorithm visualization
  
- **interpretation/**: Interpretation frameworks
  - Will contain LLM-based tools for interpreting topological features

- **gcam_to_tda.py**: Converts GCAM outputs to formats suitable for TDA

## Usage

### Running the Sampling Workflow

```bash
python sampling/run_sampling_workflow.py --method lhs --samples 50 --gcam-root ../gcam-core
```

Available sampling methods:
- `lhs`: Latin Hypercube Sampling
- `sobol`: Sobol sequence
- `random`: Random sampling
- `halton`: Halton sequence
- `orthogonal`: Orthogonal sampling

### Converting GCAM Outputs

```bash
python gcam_to_tda.py --output-dir path/to/gcam/outputs \
                      --batch-file path/to/parameter_sampling_batch.xml \
                      --query-names temperature emissions gdp energy \
                      --output-file ../outputs/scenarios/unified_results.csv
```

### Performing Persistence Homology Analysis

```python
from tda.persistence_analysis import PersistenceAnalyzer

# Initialize analyzer
analyzer = PersistenceAnalyzer("../outputs/scenarios")

# Load data
data = analyzer.load_data("unified_results.csv")

# Compute persistence diagrams
analyzer.compute_persistence(["temperature_final", "emissions_cumulative", "gdp_growth_rate"])

# Plot persistence diagram
analyzer.plot_persistence_diagram(dimension=1, save_path="../outputs/topology/persistence_dim1.png")
```

### Creating Mapper Visualizations

```python
from visualization.mapper_visualization import MapperVisualizer

# Initialize visualizer
visualizer = MapperVisualizer("../outputs/scenarios")

# Load data
visualizer.load_data("unified_results.csv")

# Compute Mapper graph
visualizer.compute_mapper(["temperature_final", "emissions_cumulative", "gdp_growth_rate"])

# Visualize
visualizer.visualize(save_path="../outputs/topology/mapper_graph.html")

# Extract network for further analysis
G = visualizer.extract_network()
metrics = visualizer.analyze_network(G)
print(metrics)
```

## Requirements

This framework requires several Python packages:

- numpy
- pandas
- matplotlib
- scikit-learn
- pyDOE2 (for sampling)
- sobol_seq (for Sobol sequences)
- gudhi (for persistent homology)
- kmapper (for Mapper algorithm)
- networkx (for graph analysis)

Install all dependencies with:

```bash
pip install -r ../requirements.txt
``` 