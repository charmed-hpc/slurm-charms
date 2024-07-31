"""Slurm Configuration Helpers."""

import copy
import textwrap
from dataclasses import dataclass, field
from typing import Optional

SLURM_CONF_SECTION_SEPARATOR = """

"""


def dedent(text: str) -> str:
    """Dedents a paragraph after removing leading and trailing whitespace."""
    return textwrap.dedent(text).lstrip()


def conjoin(*items: str, join_str: str = "\n") -> str:
    """Join strings supplied as args.

    Helper that wraps ``str.join()`` without having to pack strings in an iterable.
    """
    return join_str.join(items)


def dedent_all(*texts: str, join_str: str = "\n") -> str:
    """Dedents each blob supplied as an argument and then joins them."""
    return conjoin(*(dedent(b) for b in texts), join_str=join_str)


@dataclass
class Parameters:
    """Slurm configuration parameters."""

    AccountingStorageBackupHost: Optional[str] = None
    AccountingStorageEnforce: Optional[str] = None
    AccountingStorageExternalHost: Optional[str] = None
    AccountingStorageHost: Optional[str] = None
    AccountingStorageParameters: Optional[str] = None
    AccountingStoragePass: Optional[str] = None
    AccountingStoragePort: Optional[str] = None
    AccountingStorageTRES: Optional[str] = None
    AccountingStorageType: Optional[str] = None
    AccountingStorageUser: Optional[str] = None
    AccountingStoreFlags: Optional[str] = None
    AcctGatherNodeFreq: Optional[str] = None
    AcctGatherEnergyType: Optional[str] = None
    AcctGatherInterconnectType: Optional[str] = None
    AcctGatherFilesystemType: Optional[str] = None
    AcctGatherProfileType: Optional[str] = None
    AllowSpecResourcesUsage: Optional[str] = None
    AuthAltTypes: Optional[str] = None
    AuthAltParameters: Optional[str] = None
    AuthInfo: Optional[str] = None
    AuthType: Optional[str] = None
    BatchStartTimeout: Optional[str] = None
    BcastExclude: Optional[str] = None
    BcastParameters: Optional[str] = None
    BurstBufferType: Optional[str] = None
    CliFilterPlugins: Optional[str] = None
    ClusterName: Optional[str] = None
    CommunicationParameters: Optional[str] = None
    CheckGhalQuiesce: Optional[str] = None
    DisableIPv4: Optional[str] = None
    EnableIPv6: Optional[str] = None
    NoCtldInAddrAny: Optional[str] = None
    NoInAddrAny: Optional[str] = None
    CompleteWait: Optional[str] = None
    CoreSpecPlugin: Optional[str] = None
    CpuFreqDef: Optional[str] = None
    CpuFreqGovernors: Optional[str] = None
    CredType: Optional[str] = None
    DebugFlags: Optional[str] = None
    BurstBuffer: Optional[str] = None
    DefCpuPerGPU: Optional[str] = None
    DefMemPerCPU: Optional[str] = None
    DefMemPerGPU: Optional[str] = None
    DefMemPerNode: Optional[str] = None
    DependencyParameters: Optional[str] = None
    DisableRootJobs: Optional[str] = None
    EioTimeout: Optional[str] = None
    EnforcePartLimits: Optional[str] = None
    Epilog: Optional[str] = None
    EpilogMsgTime: Optional[str] = None
    EpilogSlurmctld: Optional[str] = None
    FairShareDampeningFactor: Optional[str] = None
    FederationParameters: Optional[str] = None
    FirstJobId: Optional[str] = None
    GetEnvTimeout: Optional[str] = None
    GresTypes: Optional[str] = None
    GroupUpdateForce: Optional[str] = None
    GroupUpdateTime: Optional[str] = None
    GpuFreqDef: Optional[str] = None
    HealthCheckInterval: Optional[str] = None
    HealthCheckNodeState: Optional[str] = None
    HealthCheckProgram: Optional[str] = None
    InactiveLimit: Optional[str] = None
    InteractiveStepOptions: Optional[str] = None
    JobAcctGatherType: Optional[str] = None
    JobAcctGatherFrequency: Optional[str] = None
    JobAcctGatherParams: Optional[str] = None
    NoShared: Optional[str] = None
    UsePss: Optional[str] = None
    OverMemoryKill: Optional[str] = None
    DisableGPUAcct: Optional[str] = None
    JobCompHost: Optional[str] = None
    JobCompLoc: Optional[str] = None
    JobCompParams: Optional[str] = None
    JobCompPass: Optional[str] = None
    JobCompPort: Optional[str] = None
    JobCompType: Optional[str] = None
    JobCompUser: Optional[str] = None
    JobContainerType: Optional[str] = None
    JobFileAppend: Optional[str] = None
    JobRequeue: Optional[str] = None
    JobSubmitPlugins: Optional[str] = None
    KillOnBadExit: Optional[str] = None
    KillWait: Optional[str] = None
    MaxBatchRequeue: Optional[str] = None
    NodeFeaturesPlugins: Optional[str] = None
    LaunchParameters: Optional[str] = None
    Licenses: Optional[str] = None
    LogTimeFormat: Optional[str] = None
    MailDomain: Optional[str] = None
    MailProg: Optional[str] = None
    MaxArraySize: Optional[str] = None
    MaxDBDMsgs: Optional[str] = None
    MaxJobCount: Optional[str] = None
    MaxJobId: Optional[str] = None
    MaxMemPerCPU: Optional[str] = None
    MaxMemPerNode: Optional[str] = None
    MaxNodeCount: Optional[str] = None
    MaxStepCount: Optional[str] = None
    MaxTasksPerNode: Optional[str] = None
    MCSParameters: Optional[str] = None
    MCSPlugin: Optional[str] = None
    MessageTimeout: Optional[str] = None
    MinJobAge: Optional[str] = None
    MpiDefault: Optional[str] = None
    MpiParams: Optional[str] = None
    OverTimeLimit: Optional[str] = None
    PluginDir: Optional[str] = None
    PlugStackConfig: Optional[str] = None
    PowerParameters: Optional[str] = None
    PowerPlugin: Optional[str] = None
    PreemptMode: Optional[str] = None
    PreemptParameters: Optional[str] = None
    PreemptType: Optional[str] = None
    PreemptExemptTime: Optional[str] = None
    PrEpParameters: Optional[str] = None
    PrEpPlugins: Optional[str] = None
    PriorityCalcPeriod: Optional[str] = None
    PriorityDecayHalfLife: Optional[str] = None
    PriorityFavorSmall: Optional[str] = None
    PriorityFlags: Optional[str] = None
    PriorityMaxAge: Optional[str] = None
    PriorityParameters: Optional[str] = None
    PrioritySiteFactorParameters: Optional[str] = None
    PrioritySiteFactorPlugin: Optional[str] = None
    PriorityType: Optional[str] = None
    PriorityUsageResetPeriod: Optional[str] = None
    PriorityWeightAge: Optional[str] = None
    PriorityWeightAssoc: Optional[str] = None
    PriorityWeightFairshare: Optional[str] = None
    PriorityWeightJobSize: Optional[str] = None
    PriorityWeightPartition: Optional[str] = None
    PriorityWeightQOS: Optional[str] = None
    PriorityWeightTRES: Optional[str] = None
    PrivateData: Optional[str] = None
    ProctrackType: Optional[str] = None
    Prolog: Optional[str] = None
    PrologEpilogTimeout: Optional[str] = None
    PrologFlags: Optional[str] = None
    PrologSlurmctld: Optional[str] = None
    PropagatePrioProcess: Optional[str] = None
    PropagateResourceLimits: Optional[str] = None
    PropagateResourceLimitsExcept: Optional[str] = None
    RebootProgram: Optional[str] = None
    ReconfigFlags: Optional[str] = None
    KeepPartInfo: Optional[str] = None
    KeepPartState: Optional[str] = None
    KeepPowerSaveSettings: Optional[str] = None
    RequeueExit: Optional[str] = None
    RequeueExitHold: Optional[str] = None
    ResumeFailProgram: Optional[str] = None
    ResumeProgram: Optional[str] = None
    ResumeRate: Optional[str] = None
    ResumeTimeout: Optional[str] = None
    ResvEpilog: Optional[str] = None
    ResvOverRun: Optional[str] = None
    ResvProlog: Optional[str] = None
    ReturnToService: Optional[str] = None
    SchedulerParameters: Optional[str] = None
    SchedulerTimeSlice: Optional[str] = None
    SchedulerType: Optional[str] = None
    ScronParameters: Optional[str] = None
    SelectType: Optional[str] = None
    SelectTypeParameters: Optional[str] = None
    SlurmctldAddr: Optional[str] = None
    SlurmctldDebug: Optional[str] = None
    SlurmctldHost: Optional[str] = None
    SlurmctldLogFile: Optional[str] = None
    SlurmctldParameters: Optional[str] = None
    SlurmctldPidFile: Optional[str] = None
    SlurmctldPort: Optional[str] = None
    SlurmctldPrimaryOffProg: Optional[str] = None
    SlurmctldPrimaryOnProg: Optional[str] = None
    SlurmctldSyslogDebug: Optional[str] = None
    SlurmctldTimeout: Optional[str] = None
    SlurmdDebug: Optional[str] = None
    SlurmdLogFile: Optional[str] = None
    SlurmdParameters: Optional[str] = None
    SlurmdPidFile: Optional[str] = None
    SlurmdPort: Optional[str] = None
    SlurmdSpoolDir: Optional[str] = None
    SlurmdSyslogDebug: Optional[str] = None
    SlurmdTimeout: Optional[str] = None
    SlurmdUser: Optional[str] = None
    SlurmSchedLogFile: Optional[str] = None
    SlurmSchedLogLevel: Optional[str] = None
    SlurmUser: Optional[str] = None
    SrunEpilog: Optional[str] = None
    SrunPortRange: Optional[str] = None
    SrunProlog: Optional[str] = None
    StateSaveLocation: Optional[str] = None
    SuspendExcNodes: Optional[str] = None
    SuspendExcParts: Optional[str] = None
    SuspendExcStates: Optional[str] = None
    SuspendProgram: Optional[str] = None
    SuspendRate: Optional[str] = None
    SuspendTime: Optional[str] = None
    SuspendTimeout: Optional[str] = None
    SwitchParameters: Optional[str] = None
    SwitchType: Optional[str] = None
    TaskEpilog: Optional[str] = None
    TaskPlugin: Optional[str] = None
    TaskPluginParam: Optional[str] = None
    Cores: Optional[str] = None
    Sockets: Optional[str] = None
    Threads: Optional[str] = None
    SlurmdOffSpec: Optional[str] = None
    Verbose: Optional[str] = None
    Autobind: Optional[str] = None
    TaskProlog: Optional[str] = None
    TCPTimeout: Optional[str] = None
    TmpFS: Optional[str] = None
    TopologyParam: Optional[str] = None
    Dragonfly: Optional[str] = None
    RoutePart: Optional[str] = None
    SwitchAsNodeRank: Optional[str] = None
    RouteTree: Optional[str] = None
    TopoOptional: Optional[str] = None
    TopologyPlugin: Optional[str] = None
    TrackWCKey: Optional[str] = None
    TreeWidth: Optional[str] = None
    UnkillableStepProgram: Optional[str] = None
    UnkillableStepTimeout: Optional[str] = None
    UsePAM: Optional[str] = None
    VSizeFactor: Optional[str] = None
    WaitTime: Optional[str] = None
    X11Parameters: Optional[str] = None

    def as_slurm_conf_entries(self):
        """Convert the parameters dict to slurm.conf parameters entries."""
        return "\n".join(f"{k}={v}" for k, v in vars(self).items() if v is not None)


@dataclass
class Partition:
    """A slurm partition."""

    PartitionName: str
    AllocNodes: Optional[str] = None
    AllowAccounts: Optional[str] = None
    AllowGroups: Optional[str] = None
    AllowQos: Optional[str] = None
    Alternate: Optional[str] = None
    CpuBind: Optional[str] = None
    Default: Optional[str] = None
    DefaultTime: Optional[str] = None
    DefCpuPerGPU: Optional[str] = None
    DefMemPerCPU: Optional[str] = None
    DefMemPerGPU: Optional[str] = None
    DefMemPerNode: Optional[str] = None
    DenyAccounts: Optional[str] = None
    DenyQos: Optional[str] = None
    DisableRootJobs: Optional[str] = None
    ExclusiveUser: Optional[str] = None
    GraceTime: Optional[str] = None
    Hidden: Optional[str] = None
    LLN: Optional[str] = None
    MaxCPUsPerNode: Optional[str] = None
    MaxCPUsPerSocket: Optional[str] = None
    MaxMemPerCPU: Optional[str] = None
    MaxMemPerNode: Optional[str] = None
    MaxNodes: Optional[str] = None
    MaxTime: Optional[str] = None
    MinNodes: Optional[str] = None
    Nodes: list[str] = field(default_factory=list)
    OverSubscribe: Optional[str] = None
    OverTimeLimit: Optional[str] = None
    PowerDownOnIdle: Optional[str] = None
    PreemptMode: Optional[str] = None
    PriorityJobFactor: Optional[str] = None
    PriorityTier: Optional[str] = None
    QOS: Optional[str] = None
    ReqResv: Optional[str] = None
    ResumeTimeout: Optional[str] = None
    RootOnly: Optional[str] = None
    SelectTypeParameters: Optional[str] = None
    State: Optional[str] = None
    SuspendTime: Optional[str] = None
    SuspendTimeout: Optional[str] = None
    TRESBillingWeights: Optional[str] = None

    def as_slurm_conf_entry(self) -> str:
        """Return slurm.conf partition entry as string."""
        partition_parameters = copy.deepcopy(vars(self))
        partition_name = partition_parameters.pop("PartitionName")
        nodes = partition_parameters.pop("Nodes")

        return (
            f"PartitionName={partition_name} "
            + "Nodes=%s " % (",".join(nodes) if len(nodes) > 0 else '""')
            + " ".join([f"{k}={v}" for k, v in partition_parameters.items() if v is not None])
        )


@dataclass
class Node:
    """A slurm node entry."""

    NodeName: str
    NodeHostname: Optional[str] = None
    NodeAddr: Optional[str] = None
    BcastAddr: Optional[str] = None
    Boards: Optional[str] = None
    CoreSpecCount: Optional[str] = None
    CoresPerSocket: Optional[str] = None
    CpuBind: Optional[str] = None
    CPUs: Optional[str] = None
    CpuSpecList: Optional[str] = None
    Features: Optional[str] = None
    Gres: Optional[str] = None
    MemSpecLimit: Optional[str] = None
    Port: Optional[str] = None
    Procs: Optional[str] = None
    RealMemory: Optional[str] = None
    Reason: Optional[str] = None
    Sockets: Optional[str] = None
    SocketsPerBoard: Optional[str] = None
    State: Optional[str] = None
    ThreadsPerCore: Optional[str] = None
    TmpDisk: Optional[str] = None
    Weight: Optional[str] = None

    def as_slurm_conf_entry(self) -> str:
        """Convert the node dict into slurm.conf entry."""
        return " ".join(f"{k}={v}" for k, v in vars(self).items() if v is not None)


@dataclass
class DownNodes:
    """A slurm DownNode entry."""

    State: str
    Reason: str
    DownNodes: list[str] = field(default_factory=list)

    def as_slurm_conf_entry(self) -> str:
        """Convert the down_nodes list into slurm.conf entries."""
        return (
            f"DownNodes={','.join(node for node in self.DownNodes)} "
            f"State={self.State} "
            f'Reason="{self.Reason}"'
        )


def slurm_conf_as_string(slurm_conf: dict) -> str:
    """Return the slurm.conf as a string."""
    slurm_conf = copy.deepcopy(slurm_conf)

    partition_entries = ["PartitionName=DEFAULT Default=YES"]

    partitions = slurm_conf.pop("partitions")
    if len(partitions) > 0:
        partition_entries = [
            Partition(partition, **partitions[partition]).as_slurm_conf_entry()
            for partition in partitions
        ]

    nodes = slurm_conf.pop("nodes")
    node_entries = [Node(node, **nodes[node]).as_slurm_conf_entry() for node in nodes]
    down_nodes = slurm_conf.pop("down_nodes")
    down_node_entries = [DownNodes(**down_node).as_slurm_conf_entry() for down_node in down_nodes]

    parameters = Parameters(**slurm_conf)

    return dedent_all(
        *[
            "# Parameters",
            parameters.as_slurm_conf_entries(),
            SLURM_CONF_SECTION_SEPARATOR,
            "# Partitions",
            "\n".join(partition_entries),
            SLURM_CONF_SECTION_SEPARATOR,
            "# Nodes",
            "\n".join(node_entries),
            SLURM_CONF_SECTION_SEPARATOR,
            "# DownNodes",
            "\n".join(down_node_entries),
        ]
    )
