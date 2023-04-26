import asyncio

import aiohttp
import web3.main
from pyuseragents import random as random_useragent
from web3 import Web3
from web3.auto import w3
from web3.eth import AsyncEth
from web3.types import TxParams

import settings.config
from utils import bypass_errors
from utils import get_address
from utils import get_gwei, get_nonce, get_chain_id
from utils import logger
from utils import read_abi

headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,'
              'image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'accept-language': 'ru,en;q=0.9,vi;q=0.8,es;q=0.7,cy;q=0.6'
}


class TokensClaimer:
    def __init__(self,
                 private_key: str,
                 address: str):
        self.claim_contract = None
        self.config_json: dict | None = None
        self.provider: web3.main.Web3 | None = None
        self.address: str = address
        self.private_key: str = private_key

    async def get_transaction_data(self) -> list:
        while True:
            try:
                async with aiohttp.ClientSession(headers={
                    **headers,
                    'user-agent': random_useragent()
                }) as session:
                    r = await bypass_errors(target_function=session.get,
                                            url='https://api.arbdrop.one/proof',
                                            params={
                                                'address': self.address
                                            })

                    if type(await r.json()) != list:
                        logger.error(f'{self.address} | {self.private_key} - Wrong Response: {await r.text()}')
                        continue

                    return await r.json()

            except Exception as error:
                logger.error(f'{self.address} | {self.private_key} - Unexpected Error: {error}')

    async def send_transaction(self,
                               proof: list) -> None:
        tasks = [get_nonce(provider=self.provider,
                           address=self.address),
                 get_chain_id(provider=self.provider)]

        nonce, chain_id = await asyncio.gather(*tasks)

        gwei: float = w3.from_wei(number=await get_gwei(provider=self.provider),
                                  unit='gwei') if self.config_json['GWEI_CLAIM'] == 'auto' \
            else float(self.config_json['GWEI_CLAIM'])

        if self.config_json['GAS_LIMIT_CLAIM'] == 'auto':
            transaction_data: dict = {
                'chainId': chain_id,
                'gasPrice': w3.to_wei(gwei, 'gwei'),
                'from': self.address,
                'nonce': nonce,
                'value': 0
            }

            gas_limit: int = await bypass_errors(self.claim_contract.functions.claim(
                proof,
                '0xDEADf12DE9A24b47Da0a43E1bA70B8972F5296F2'
            ).estimate_gas,
                                                 transaction=transaction_data)

            if gas_limit is None:
                return

        else:
            gas_limit: int = int(self.config_json['GAS_LIMIT_CLAIM'])

        transaction_data: dict = {
            'chainId': chain_id,
            'gasPrice': w3.to_wei(gwei, 'gwei'),
            'from': self.address,
            'nonce': nonce,
            'value': 0,
            'gas': gas_limit
        }

        transaction: TxParams = await bypass_errors(self.claim_contract.functions.claim(
            proof,
            '0xDEADf12DE9A24b47Da0a43E1bA70B8972F5296F2'
        ).build_transaction,
                                                    transaction=transaction_data)

        signed_transaction = self.provider.eth.account.sign_transaction(transaction_dict=transaction,
                                                                        private_key=self.private_key)

        await bypass_errors(target_function=self.provider.eth.send_raw_transaction,
                            transaction=signed_transaction.rawTransaction)

        transaction_hash: str = w3.to_hex(w3.keccak(signed_transaction.rawTransaction))
        logger.info(f'{self.address} | {self.private_key} - {transaction_hash}')

    async def start_work(self) -> None:
        self.config_json: dict = settings.config.config
        self.provider: web3.main.Web3 = Web3(Web3.AsyncHTTPProvider(self.config_json['RPC_URL']),
                                             modules={'eth': (AsyncEth,)},
                                             middlewares=[])
        self.claim_contract = self.provider.eth.contract(
            address=w3.to_checksum_address(value=self.config_json['CLAIM_CONTRACT_ADDRESS']),
            abi=await read_abi(filename='claim_abi.json'))
        proof_list: list = await self.get_transaction_data()

        if proof_list:
            await self.send_transaction(proof=proof_list)


def tokens_claimer(private_key: str) -> None:
    address = get_address(private_key=private_key)

    asyncio.run(TokensClaimer(private_key=private_key,
                              address=address).start_work())
