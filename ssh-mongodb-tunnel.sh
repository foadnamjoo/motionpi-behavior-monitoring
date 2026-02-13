#!/usr/bin/env bash
# Forward local 27017 to MongoDB on YOUR_DB_HOST.
# Run this in a separate terminal first; SSH will prompt for your CHPC password.
# Keep this terminal open, then in another terminal run: python mongodb_query.py
echo "Connecting to YOUR_DB_HOST (you will be asked for your CHPC password)..."
ssh -N -L 27017:127.0.0.1:27017 YOUR_UNID@YOUR_DB_HOST
