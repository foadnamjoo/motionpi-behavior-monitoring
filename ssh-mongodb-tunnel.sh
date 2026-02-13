#!/usr/bin/env bash
# Example: forward local 27017 to a remote MongoDB. Customize for your environment.
# Set SSH_TUNNEL_HOST and SSH_TUNNEL_USER in your environment (or edit below for local use only).
# Run in a separate terminal; SSH will prompt for password. Keep it open while querying.
: "${SSH_TUNNEL_HOST:=your-mongo-host.example.com}"
: "${SSH_TUNNEL_USER:=your-username}"
echo "Connecting to $SSH_TUNNEL_HOST (you will be asked for your password)..."
ssh -N -L 27017:127.0.0.1:27017 "${SSH_TUNNEL_USER}@${SSH_TUNNEL_HOST}"
