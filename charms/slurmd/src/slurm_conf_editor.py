#!/usr/bin/env python3
"""Slurm Node Options."""
from dataclasses import dataclass


@dataclass
class Partition:
    """A slurm partition."""

    PartitionName: str
    AllocNodes: str
    AllowAccounts: str
    AllowGroups: str
    AllowQos: str
    Alternate: str
    CpuBind: str
    Default: str
    DefaultTime: str
    DefCpuPerGPU: str
    DefMemPerCPU: str
    DefMemPerGPU: str
    DefMemPerNode: str
    DenyAccounts: str
    DenyQos: str
    DisableRootJobs: str
    ExclusiveUser: str
    GraceTime: str
    Hidden: str
    LLN: str
    MaxCPUsPerNode: str
    MaxCPUsPerSocket: str
    MaxMemPerCPU: str
    MaxMemPerNode: str
    MaxNodes: str
    MaxTime: str
    MinNodes: str
    Nodes: str
    OverSubscribe: str
    OverTimeLimit: str
    PowerDownOnIdle: str
    PreemptMode: str
    PriorityJobFactor: str
    PriorityTier: str
    QOS: str
    ReqResv: str
    ResumeTimeout: str
    RootOnly: str
    SelectTypeParameters: str
    State: str
    SuspendTime: str
    SuspendTimeout: str
    TRESBillingWeights: str


@dataclass
class Node:
    """A slurm node entry."""

    NodeName: str
    NodeHostname: str
    NodeAddr: str
    BcastAddr: str
    Boards: str
    CoreSpecCount: str
    CoresPerSocket: str
    CpuBind: str
    CPUs: str
    CpuSpecList: str
    Features: str
    Gres: str
    MemSpecLimit: str
    Port: str
    Procs: str
    RealMemory: str
    Reason: str
    Sockets: str
    SocketsPerBoard: str
    State: str
    ThreadsPerCore: str
    TmpDisk: str
    Weight: str
