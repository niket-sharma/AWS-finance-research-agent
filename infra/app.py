#!/usr/bin/env python3
"""CDK app entry point."""
import aws_cdk as cdk
from phase0_runtime_gateway.stack import Phase0Stack
from phase1_knowledge_base.stack import Phase1Stack

app = cdk.App()
env = cdk.Environment(account="911634252933", region="us-east-1")
Phase0Stack(app, "ResearchDeskPhase0", env=env)
Phase1Stack(app, "ResearchDeskPhase1", env=env)
app.synth()
