#!/bin/bash

# TPC-DS Data Generation Script with Parallelism
# Usage: ./generate_data.sh <directory> <scale_factor>

set -e

if [ $# -ne 3 ]; then
    echo "Usage: $0 <directory> <scale_factor> <parallelism>"
    echo "Example: $0 /tmp/tpcds_data 1 8"
    exit 1
fi

DIR="$1"
SCALE="$2"
PARALLEL="$3"

echo "Starting TPC-DS data generation..."
echo "Directory: $DIR"
echo "Scale Factor: $SCALE"
echo "Parallelism: $PARALLEL"
echo

# Create directory if it doesn't exist
mkdir -p "$DIR"

# Start timing
start_time=$(date +%s)

# Launch parallel processes
for i in $(seq 1 $PARALLEL); do
    echo "Starting child process $i..."
    ./dsdgen -dir "$DIR" -scale "$SCALE" -parallel "$PARALLEL" -child "$i" &
done

# Wait for all background processes to complete
wait

# End timing
end_time=$(date +%s)
duration=$((end_time - start_time))

echo
echo "Data generation completed!"
echo "Total time: ${duration} seconds"
echo "Generated data location: $DIR"
