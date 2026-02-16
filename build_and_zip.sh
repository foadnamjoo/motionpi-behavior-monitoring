#!/bin/bash
# Build the MotionPI Report app and zip it with config for your MongoDB.
# Run from project root: ./build_and_zip.sh
# Output: MotionPI_Report_Mac.zip (contains "MotionPI Report" + config.env)

set -e
cd "$(dirname "$0")"

echo "Building app..."
pyinstaller MotionPI_Report.spec

echo "Adding config.env template into dist/..."
cp env.dist dist/config.env
cp README_for_zip.txt dist/README.txt

echo "Creating zip..."
cd dist
zip -r ../MotionPI_Report_Mac.zip "MotionPI Report" config.env README.txt
cd ..

echo "Done. Send MotionPI_Report_Mac.zip to users."
echo "They unzip and see: MotionPI Report + config.env. Run the app from that folder."
