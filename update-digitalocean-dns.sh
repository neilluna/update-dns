#!/usr/bin/env bash

script_version=1.0.0

script_name=$(basename ${BASH_SOURCE[0]})
script_dir=$(dirname ${BASH_SOURCE[0]})
script_path=${BASH_SOURCE[0]}

function echo_usage()
{ 
	echo "${script_name} - Version ${script_version}"
	echo ""
	echo "This script will update the DigitalOcean DNS servers if the public IPv4 address"
    echo "of this server changes."
	echo ""
	echo "Usage: ${script_name} [options] configuration-file"
	echo ""
	echo "                      Options:"
	echo "  -h, --help          Output this help information and exit."
	echo "      --nocolor       Do not color output."
	echo "      --syslog        Send errors to syslog. Implies the --nocolor option."
	echo "  -v, --verbose       Verbose output."
	echo "      --version       Output the version and exit."
	echo ""
	echo "  configuration-file  Path to the configuration file."
} 

# ANSI color escape sequences for use in echo_color().
black='\e[30m'
red='\e[31m'
green='\e[32m'
yellow='\e[33m'
blue='\e[34m'
magenta='\e[35m'
cyan='\e[36m'
white='\e[37m'
reset='\e[0m'

# Echo a message.
# Color is ignored if the usecolor variable is not set to "yes".
# Usage: echo_message color message
function echo_message()
{
	color=${1}
	message=${2}
	if [ ${usecolor} == yes ]; then
		echo_color ${color} "${message}"
	else
		echo -e "${message}"
	fi
}

# Echo a color message.
# Echoing ANSI escape codes for color works, yet tput does not.
# This may be caused by tput not being able to determine the terminal type.
# Usage: echo_color color message
function echo_color()
{
	color=${1}
	message=${2}
	echo -e "$(eval echo \$$color)${message}${reset}"
}

# Echo an informational message.
# Usage: echo_info message
function echo_info()
{
	message=${1}
	echo_message cyan "${message}"
}

# Echo an error message to stderr or syslog.
# Usage: echo_error message
function echo_error()
{
	message=${1}
	if [ ${send_errors_to_syslog} == yes ]; then
		logger -i "${script_name}: ${message}"
	else
		echo_message red "${message}" >&2
	fi
}

# Echo an error message and exit.
# Usage: echo_error_and_exit message
function echo_error_and_exit()
{
	message=${1}
	echo_error "${message}"
	exit 1
}

# Get the record id of a DNS record of the domain, given name, and type.
# Usage: get_record_id domain record_name record_type
function get_record_id()
{ 
	domain=${1}
	record_name=${2}
	record_type=${3}
    record_id=$(curl -sX GET -H 'Content-Type: application/json' -H 'Authorization: Bearer '${personal_access_token} https://api.digitalocean.com/v2/domains/${domain}/records/ | jq -er '[.domain_records[] | select(.name=="'${record_name}'") | select(.type=="'${record_type}'") | .id][0]')
    if [ ${?} -ne 0 ]; then
        echo_error_and_exit "Error getting record ID from DigitalOcean."
    fi
    if [ -z $(echo "${record_id}" | egrep '^[0-9]+$') ]; then
        echo_error_and_exit "Invalid record ID: ${record_id}"
    fi
}

# Command-line switch variables.
configuration_file=
send_errors_to_syslog=no
usecolor=yes
verbose=no

# NOTE: This requires GNU getopt. On Mac OS X and FreeBSD, you have to install this separately.
ARGS=$(getopt -o hv -l help,nocolor,syslog,verbose,version -n ${script_name} -- "${@}")
if [ ${?} != 0 ]; then
	exit 1
fi

# The quotes around "${ARGS}" are necessary.
eval set -- "${ARGS}"

# Parse the command line arguments.
while true; do
	case "${1}" in
		-h | --help)
			echo_usage
			exit 0
			;;
		--nocolor)
			usecolor=no
			shift
			;;
		--syslog)
			send_errors_to_syslog=yes
			shift
			;;
		-v | --verbose)
			verbose=yes
			shift
			;;
		--version)
			echo "${script_version}"
			exit 0
			;;
		--)
			shift
			break
			;;
	esac
done
while [ ${#} -gt 0 ]; do
	if [ -z "${configuration_file}" ]; then
		configuration_file=${1}
	else
		echo_error "Invalid argument: ${1}"
		echo_usage
		exit 1
	fi
	shift
done
if [ -z "${configuration_file}" ]; then
	echo_error "Missing configuration-file parameter."
	echo_usage ${0}
	exit 1
fi

# Smoke test of configuration file.
if [ ! -f ${configuration_file} ]; then
	echo_error_and_exit "Missing configuration file."
fi
jq -er '.' ${configuration_file} > /dev/null
if [ ${?} -ne 0 ]; then
    echo_error_and_exit "Errors in configuration file."
fi

personal_access_token_file=$(jq -er '.personal_access_token_file' ${configuration_file})
public_ip_address_log_file=$(jq -er '.public_ip_address_log_file' ${configuration_file})

personal_access_token=$(tail -1 ${personal_access_token_file})

# Get the public IP address of this system.
public_ip_address=$(dig +short myip.opendns.com @resolver1.opendns.com)
if [ ${?} -ne 0 ]; then
    echo_error_and_exit "Error getting public IP address from opendns.com."
fi

# Make sure that the public ip address is a valid IPv4 address.
if [ -z $(echo "${public_ip_address}" | egrep '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$') ]; then
    echo_error_and_exit "Invalid public IPv4 address: ${public_ip_address}"
fi
octets=($(echo ${public_ip_address} | awk 'BEGIN {RS = "."}; {print $1}'))
if [ ${octets[0]} -gt 255 -o ${octets[1]} -gt 255 -o ${octets[2]} -gt 255 -o ${octets[3]} -gt 255 ]; then
    echo_error_and_exit "Invalid public IPv4 address: ${public_ip_address}"
fi
[ ${verbose} == yes ] && echo_info "The public IP address is ${public_ip_address}"

# Get the last public ip address from the log file.
if [ -f ${public_ip_address_log_file} ]; then
	last_public_ip_address=$(tail -1 ${public_ip_address_log_file} | awk '{print $3}')
else
	last_public_ip_address="not set."
fi
[ ${verbose} == yes ] && echo_info "The last public IP address was ${last_public_ip_address}"

# If the public ip address has changed, then update the DNS server.
if [ "${public_ip_address}" != "${last_public_ip_address}" ]; then

    # For each domain that we need to update...
    domain_count=$(jq -er '.domains | length' ${configuration_file})
    for domain_index in $(seq 0 $(expr ${domain_count} - 1)); do
        domain=$(jq -er '.domains['${domain_index}'].domain' ${configuration_file})

        # For each record in the domain that we need to update...
        record_count=$(jq -er '.domains['${domain_index}'].records | length' ${configuration_file})
        for record_index in $(seq 0 $(expr ${record_count} - 1)); do
            record_name=$(jq -er '.domains['${domain_index}'].records['${record_index}'].name' ${configuration_file})
            record_type=$(jq -er '.domains['${domain_index}'].records['${record_index}'].type' ${configuration_file})
            get_record_id ${domain} ${record_name} ${record_type}
			[ ${verbose} == yes ] && echo_info "Updating DigitalOcean DNS domain ${domain}, record ${record_id} ..."
	        curl -sX PUT -H "Content-Type: application/json" -H "Authorization: Bearer ${personal_access_token}" -d '{"data":"'${public_ip_address}'"}' "https://api.digitalocean.com/v2/domains/${domain}/records/${record_id}" > /dev/null
            if [ ${?} -ne 0 ]; then
                echo_error_and_exit "Error updating DigitalOcean DNS domain ${domain}, record ID ${record_id}."
            fi
        done
    done
    echo "$(date --rfc-3339=seconds) ${public_ip_address}" >> ${public_ip_address_log_file}
	[ ${verbose} == yes ] && echo_info "All updates performed."
else
	[ ${verbose} == yes ] && echo_info "No updates performed."
fi

exit 0
