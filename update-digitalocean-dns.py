#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import syslog
import time

from rfc3339 import rfc3339

import digitalocean


SCRIPT_VERSION = '3.0.0'
SCRIPT_NAME = os.path.basename(__file__)


def print_usage():
    ''' Print the program usage. '''
    print(f'{SCRIPT_NAME} - Version {SCRIPT_VERSION}')
    print('')
    print('This script will update the DigitalOcean DNS servers if the public IPv4 address')
    print('of this server changes.')
    print('')
    print(f'Usage: {SCRIPT_NAME} path-to-the-configuration-file')


class PrintHelper():
    ''' Miscellaneous print methods. '''

    # ANSI color escape sequences.
    colors_codes = {
        'black': '\u001b[30m',
        'red': '\u001b[31m',
        'green': '\u001b[32m',
        'yellow': '\u001b[33m',
        'blue': '\u001b[34m',
        'magenta': '\u001b[35m',
        'cyan': '\u001b[36m',
        'white': '\u001b[37m',
        'reset': '\u001b[0m',
    }


    def __init__(self, send_in_color=False, send_to_syslog=False):
        self.send_in_color = send_in_color
        self.send_to_syslog = send_to_syslog
        if send_to_syslog:
            syslog.openlog(ident=SCRIPT_NAME, logoption=syslog.LOG_PID)


    def error(self, message):
        ''' Print an error message. '''
        self.send_message(message, 'red', True, syslog.LOG_ERR)


    def error_and_exit(self, message):
        ''' Print an error message and exit the program. '''
        self.send_message(message, 'red', True, syslog.LOG_ERR)
        sys.exit(1)


    def info(self, message):
        ''' Print an information message. '''
        self.send_message(message, 'cyan', False, syslog.LOG_INFO)


    def send_message(self, message, color, send_to_stderr, syslog_level):
        ''' Print a message '''
        if self.send_to_syslog:
            syslog.syslog(syslog_level, f'{message}')
            return
        if self.send_in_color:
            message = f"{self.colors_codes[color]}{message}{self.colors_codes['reset']}"
        if send_to_stderr:
            print(message, file=sys.stderr)
        else:
            print(message)


    def warning(self, message):
        ''' Print an error message. '''
        self.send_message(message, 'yellow', True, syslog.LOG_WARNING)


class DNSUpdater():
    ''' DNS update methods. '''


    def __init__(self, configuration):
        self.configuration = configuration
        send_in_color = self.configuration['messages']['send_in_color']
        send_to_syslog = self.configuration['messages']['send_to_syslog']
        self.print = PrintHelper(send_in_color, send_to_syslog)
        self.verbose = configuration['messages']['verbose']

        self.public_ip_address = self.get_public_ip_address()

        self.public_ip_address_log_file = configuration['public_ip_address_log_file']
        self.last_public_ip_address = self.read_last_public_ip_address()


    def get_public_ip_address(self):
        ''' Get the public IP address. '''

        # Get the public IP address of this system.
        command = 'dig +short myip.opendns.com @resolver1.opendns.com'
        results = subprocess.run(command, capture_output=True, check=False, shell=True, text=True)
        if results.returncode != 0:
            self.print.error_and_exit('Error getting public IP address from opendns.com.')
        ip_address = results.stdout.rstrip()

        # Make sure that the public ip address is a valid IPv4 address.
        octets = ip_address.split('.')
        if len(octets) != 4:
            self.print.error_and_exit(f'Invalid public IPv4 address: {ip_address}')
        for octet in octets:
            if not octet.isdigit() or int(octet) < 0 or int(octet) > 255:
                self.print.error_and_exit(f'Invalid public IPv4 address: {ip_address}')
        if self.verbose:
            self.print.info(f'The public IP address is {ip_address}')
        return ip_address


    def read_last_public_ip_address(self):
        ''' Read the last public ip address from the log file. '''
        try:
            with open(self.public_ip_address_log_file, mode='r', encoding='utf-8') as file:
                for line in file:
                    ip_address = line
            ip_address = ip_address.split()[-1]
        except FileNotFoundError:
            ip_address = 'not set.'
        if self.verbose:
            self.print.info(f'The last public IP address was {ip_address}')
        return ip_address


    def write_last_public_ip_address(self):
        ''' Write the last public ip address to the log file. '''
        try:
            with open(self.public_ip_address_log_file, mode='a', encoding='utf-8') as file:
                file.write(f'{rfc3339(time.time())} {self.public_ip_address}\n')
        except FileNotFoundError:
            self.print.warning('Could not update public IP address log.')


class DigitalOceanDNSUpdater(DNSUpdater):
    ''' DigitalOcean DNS update methods. '''


    def __init__(self, configuration):
        super().__init__(configuration)
        personal_access_token_file = self.configuration['personal_access_token_file']
        self.personal_access_token = self.read_access_token(personal_access_token_file)


    def read_access_token(self, filename):
        ''' Read the personal access token file. '''
        try:
            with open(filename, mode='r', encoding='utf-8') as file:
                for line in file:
                    access_token = line
            access_token = access_token.split()[-1]
        except FileNotFoundError:
            self.print.error_and_exit('Missing personal access token file.')
        return access_token


    def get_dns_records(self, domain_name):
        ''' Get the DNS records for the given domain.  '''
        dns_domain = digitalocean.Domain(token=self.personal_access_token, name=domain_name)
        return dns_domain.get_records()


    def update_dns_record(self, domain_name, dns_record, data):
        ''' Update the specified DNS record in the specified domain. '''
        if self.verbose:
            record_name = dns_record.name
            record_type = dns_record.type
            message = f'Updating DNS {domain_name}, {record_type} record {record_name} ...'
            self.print.info(message)
        dns_record.data = data
        dns_record.save()


    def update_domain_records(self, cfg_domain):
        ''' Update all the domain records in the specified configuration domain. '''
        domain_name = cfg_domain['name']
        dns_records = self.get_dns_records(domain_name)
        for cfg_record in cfg_domain['records']:
            dns_record = [
                dns_record
                for dns_record in dns_records
                if (
                    dns_record.name == cfg_record['name'] and
                    dns_record.type == cfg_record['type']
                )
            ]  # Should be only zero or one elements in this list.
            if dns_record:
                self.update_dns_record(domain_name, dns_record[0], self.public_ip_address)
            else:
                record_name = cfg_record['name']
                record_type = cfg_record['type']
                message = f'Missing DNS {domain_name}, {record_type} record {record_name} ...'
                self.print.warning(message)


class Main():
    ''' Main program. '''


    def __init__(self):
        self.print = PrintHelper(send_in_color=False, send_to_syslog=False)
        if len(sys.argv) != 2:
            self.print.error("Incorrect number of arguments.")
            print_usage()
            sys.exit(1)
        configuration_file = sys.argv[1]

        self.configuration = self.read_conguration(configuration_file)
        self.updater = DigitalOceanDNSUpdater(self.configuration)

        send_in_color = self.configuration['messages']['send_in_color']
        send_to_syslog = self.configuration['messages']['send_to_syslog']
        self.print = PrintHelper(send_in_color, send_to_syslog)
        self.verbose = self.configuration['messages']['verbose']

        if self.updater.public_ip_address != self.updater.last_public_ip_address:
            for cfg_domain in self.configuration['domains']:
                self.updater.update_domain_records(cfg_domain)
            self.updater.write_last_public_ip_address()
            if self.verbose:
                self.print.info('All updates performed.')
        elif self.verbose:
            self.print.info('No updates performed.')


    def read_conguration(self, filename):
        ''' Read the configuration file. '''
        try:
            with open(filename, mode='r', encoding='utf-8') as file:
                configuration = json.load(file)
        except FileNotFoundError:
            self.print.error_and_exit('Missing configuration file.')
        except json.decoder.JSONDecodeError as error:
            message = f'{error.msg}: line {error.lineno} column {error.colno} (char {error.pos})'
            self.print.error_and_exit(f'Error in configuration file: {message}')
        return configuration


def main():
    ''' Main program. '''
    Main()


if __name__== "__main__":
    main()
