#!/bin/bash

# TPC-DS Parallel Data Generation Script
# Usage: ./generate_parallel.sh <scale_factor> <num_processes> <output_dir>

SCALE=${1:-1}
PROCESSES=${2:-10}
OUTPUT_DIR=${3:-./tpcds_data_parallel}

echo "Starting TPC-DS parallel data generation..."
echo "Scale factor: $SCALE"
echo "Number of processes: $PROCESSES" 
echo "Output directory: $OUTPUT_DIR"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Export DIR variable for all child processes
export DIR="$OUTPUT_DIR"

echo "Generating data in $PROCESSES parallel chunks..."

# Start background processes for chunks 1 through N-1
for i in $(seq 1 $((PROCESSES-1))); do
    echo "Starting chunk $i of $PROCESSES..."
    ./dsdgen -dir "$DIR" -scale "$SCALE" -parallel "$PROCESSES" -child "$i" &
done

# Run the last chunk in foreground so we can monitor completion
echo "Starting chunk $PROCESSES of $PROCESSES (foreground)..."
./dsdgen -dir "$DIR" -scale "$SCALE" -parallel "$PROCESSES" -child "$PROCESSES"

# Wait for all background processes to complete
echo "Waiting for all background processes to complete..."
wait

echo "All chunks completed. Merging data files..."

# The individual chunks create separate files like tablename_1_10.dat, tablename_2_10.dat, etc.
# We need to concatenate them into final tablename.dat files
for table in call_center catalog_page catalog_returns catalog_sales customer customer_address customer_demographics date_dim household_demographics income_band inventory item promotion reason ship_mode store store_returns store_sales time_dim warehouse web_page web_returns web_sales web_site dbgen_version; do
    if ls "$DIR"/${table}_*_${PROCESSES}.dat 1> /dev/null 2>&1; then
        echo "Merging $table..."
        cat "$DIR"/${table}_*_${PROCESSES}.dat > "$DIR/${table}.dat"
        # Optionally remove the chunk files
        # rm "$DIR"/${table}_*_${PROCESSES}.dat
    fi
done

echo "Data generation completed successfully!"
echo "Final data files are in: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"/*.dat