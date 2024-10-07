import sys
from typing import Any

import yaml

from communex._common import get_node_url, transform_stake_dmap
from communex.balance import from_horus, from_nano
from communex.client import CommuneClient
from communex.key import check_ss58_address, is_ss58_address
from communex.cli.root import app as app
from communex.compat.key import try_classic_load_key
from communex.types import Ss58Address

module_emissions: dict[str, dict[Any, Any]]= {}

def get_emissions_info(
    client: CommuneClient
) -> dict[str, dict[Any, Any]]:

    request_dict: dict[Any, Any] = {
        "SubspaceModule": [
            ("Keys", []),
            ("Emission", []),
            ("Incentive", []),
            ("Dividends", []),
            ("Tempo", []),
            ("StakeFrom", []),
            ("SubnetNames", []),
        ],
    }

    bulk_query = client.query_batch_map(request_dict)
    (
        uid_to_key,
        uid_to_emission,
        uid_to_incentive,
        uid_to_dividend,
        netuid_to_tempo,
        ss58_to_stakefrom,
        netuid_to_subnet_name

    ) = (
        bulk_query.get("Keys", {}),
        bulk_query["Emission"],
        bulk_query["Incentive"],
        bulk_query["Dividends"],
        bulk_query["Tempo"],
        bulk_query.get("StakeFrom", {}),
        bulk_query["SubnetNames"],
    )

    miners = {}
    validators = {}
    inactive = {}
    total_stakes = {}
    ss58_to_stakefrom = transform_stake_dmap(ss58_to_stakefrom)
    for (netuid, uid), key in uid_to_key.items():
        emission = uid_to_emission[netuid][uid]
        incentive = uid_to_incentive[netuid][uid]
        dividends = uid_to_dividend[netuid][uid]

        if incentive == dividends == 0: #inactive
            module_type = inactive
        elif incentive > dividends: #miner
            module_type = miners
        else: #validator
            module_type = validators

        if key not in module_type:
            module_type[key] = {}
        module_type[key][netuid] = from_horus(emission, netuid_to_tempo[netuid])

        stake_from = ss58_to_stakefrom.get(key, [])
        total_stakes[key] = sum(stake for _, stake in stake_from)

    return {'miners': miners, 'validators': validators, 'inactive': inactive, 'total_stakes': total_stakes, 'subnet_names': netuid_to_subnet_name}


def validate_key(key: str) -> Ss58Address:
    if is_ss58_address(key):
        return  key
    else:
        try:
            keypair = try_classic_load_key(key)
            return check_ss58_address(keypair.ss58_address)
        except FileNotFoundError:
            print(f"Key file for {key} was not found.")
            exit(0)

def calc_apr(block_rewards: float, total_staked: float):
        block_time = 8  # seconds
        seconds_in_a_day = 86400
        blocks_in_a_day = seconds_in_a_day / block_time
        daily_rewards = block_rewards * blocks_in_a_day
        yearly_rewards= daily_rewards * 365
        validator_fee = 5/100 # TODO: hardcoded 5% fee, need to retrive.
        apr = yearly_rewards * (1 - validator_fee) / total_staked
        print(f"block emissions: {block_rewards}")
        print(f"daily rewards: {daily_rewards}")
        print(f"yearly rewards: {yearly_rewards}")
        print(f"total staked: {total_staked}")
        print(f"validator monthly earnings: {(yearly_rewards * validator_fee) / 12}")
        print(f"staker APR: {apr*100:.2f}%\n")


def get_module_emissions(client: CommuneClient):
    global module_emissions
    module_emissions = get_emissions_info(client)

def print_validator_rewards(key: str):
    key_address = validate_key(key)
    emissions = module_emissions["validators"].get(key_address)
    if emissions:
        print("######## VALIDATOR STATS ########\n")
        print(f"Validating on: {subnet_list_with_names(emissions.keys())}")
        # print_inactive_subnets(key)
        sum_of_all_emissions = sum(emissions.values())
        total_staked = from_nano(module_emissions['total_stakes'][key])
        calc_apr(sum_of_all_emissions, total_staked)

def print_miner_stats(block_rewards: float):
    block_time = 8  # seconds
    seconds_in_a_day = 86400
    blocks_in_a_day = seconds_in_a_day / block_time
    daily_rewards = block_rewards * blocks_in_a_day
    yearly_rewards= daily_rewards * 365
    print(f"block emissions: {block_rewards}")
    print(f"daily rewards: {daily_rewards}")
    print(f"monthly rewards: {yearly_rewards / 12}")
    print(f"yearly rewards: {yearly_rewards}\n")

def print_miner_rewards(key: str):
    # print daily, monthy, and yearly projected rewards
    key_address = validate_key(key)
    emissions = module_emissions["miners"].get(key_address)
    if emissions:
        print("######## MINER STATS ########\n")
        print(f"Mining on: {subnet_list_with_names(emissions.keys())}")
        sum_of_all_emissions = sum(emissions.values())
        print_miner_stats(sum_of_all_emissions)

def print_inactive_subnets(key: str):
    key_address = validate_key(key)
    inactive_subnets = module_emissions["inactive"].get(key_address)
    if inactive_subnets:
        print(f"Inactive on: {subnet_list_with_names(inactive_subnets.keys())}")
        print()

def print_module_stats(key: str):
    key_address = validate_key(key)
    print(f"\nKey: {key_address}\n\n")
    print_validator_rewards(key_address)
    print_miner_rewards(key_address)
    print_inactive_subnets(key_address)
    print_unregistered_subnets(key_address)

def unregistered_list(key: str):
    key_address = validate_key(key)
    subnets =  set(module_emissions["subnet_names"].keys())
    validators = module_emissions["validators"].get(key_address)
    if validators:
        subnets = subnets - set(validators)
    miners = module_emissions["miners"].get(key_address)
    if miners:
        subnets = subnets - set(miners)
    inactive = module_emissions["inactive"].get(key_address)
    if inactive:
        subnets = subnets - set(inactive)
    return list(subnets)

def print_unregistered_subnets(key: str):
    unregistered_subnets = unregistered_list(key)
    if unregistered_subnets:
        print(f"Unregistered on: {subnet_list_with_names(unregistered_subnets)}")
        print()

def subnet_list_with_names(netuids: list[int]):
    return [f"{uid}: {module_emissions["subnet_names"].get(uid)}" for uid in netuids ]

if __name__=='__main__':
    node_url = get_node_url(None, use_testnet=False)
    client = CommuneClient(url=node_url, num_connections=1, wait_for_finalization=False)
    get_module_emissions(client)
    inputArgs = sys.argv
    if len(inputArgs) > 1:
        for i in range(1, len(inputArgs)):
            print_module_stats(inputArgs[i])
    else:
        with open("modules.yml", 'r') as stream:
            modules: dict[str, dict[str, list]] = yaml.safe_load(stream)

        for key in modules:
            print_module_stats(key)
            key_address = validate_key(key)
            _validaor = modules[key].get("validator")
            if _validaor:
                key_validators = module_emissions["validators"].get(key_address)
                inactive_validators = set(_validaor)
                if key_validators:
                    inactive_validators = inactive_validators - set(key_validators.keys())
                for netuid in  inactive_validators:
                    if key_address in module_emissions["inactive"]:
                        print(f"WARNING: {key_address}{" ("+key+")" if key_address != key else ""} isn't active on subnet {netuid} ({module_emissions["subnet_names"].get(netuid)}). Expected to be an active validator.")
                    elif key_address in module_emissions["miners"]:
                        print(f"WARNING: {key_address}{" ("+key+")" if key_address != key else ""} active as a miner while expected to be active as a validator on {netuid} ({module_emissions["subnet_names"].get(netuid)}).")
                    else:
                        print(f"WARNING: {key_address}{" ("+key+")" if key_address != key else ""}is not registered on {netuid} ({module_emissions["subnet_names"].get(netuid)}).")

            _miner = modules[key].get("miner")
            if _miner:
                key_miners = module_emissions["miners"].get(key_address)
                inactive_miners = set(_miner)
                if key_miners:
                    inactive_miners = inactive_miners - set(key_miners.keys())
                for netuid in  inactive_miners:
                    if key_address in module_emissions["inactive"]:
                        print(f"WARNING: {key_address}{" ("+key+")" if key_address != key else ""} isn't active on subnet {netuid} ({module_emissions["subnet_names"].get(netuid)}). Expected to be an active miner.")
                    elif key_address in module_emissions["validators"]:
                        print(f"WARNING: {key_address}{" ("+key+")" if key_address != key else ""} active as a validator while expected to be active as a miner on {netuid} ({module_emissions["subnet_names"].get(netuid)}).")
                    else:
                        print(f"WARNING: {key_address}{" ("+key+")" if key_address != key else ""} is not registered on {netuid} ({module_emissions["subnet_names"].get(netuid)}).")
            print("\n\n\n")
