#!/usr/bin/env python3
"""CDK app entry point."""
import aws_cdk as cdk
from phase0_runtime_gateway.stack import Phase0Stack

app = cdk.App()
Phase0Stack(
    app,
    "ResearchDeskPhase0",
    env=cdk.Environment(account="911634252933", region="us-east-1"),
)
app.synth()
