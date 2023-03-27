#compdef _carl carl

function _carl {
	local line
	_arguments -C '-X:method:(GET POST PUT DELETE PATCH)' '1:url:{_carl_url}' '*::parameter:{_carl_params}'
	# echo
	# echo context=$context state=$state state_descr=$state_descr line=$line
	# sleep 5
}

function _carl_utils {
	python -m curl_arguments_url.complete_util $*
}

function _carl_url {
    eval "values=($(_carl_utils urls $opt_args[-X] | sed 's/:/\\:/g'))"

    if [[ $values ]]; then
	    _describe url $values
	fi
}

function _carl_params {
	local url param_args arguments

	url=$(bash -c 'echo '$line[1])
	if [[ $opt_args[-X] ]]; then
		param_args=(-X $opt_args[-X])
	fi

    eval "arguments=($(_carl_utils params  "$param_args[@]" --format '+{param}:value:{{_carl_param_values\ {param}}}' "$(printf '%b' $url)"))"
	if [[ "$arguments" ]]; then
        _arguments $arguments
    fi
}

function _carl_param_values {
	local values param
	param=$1
	eval "values=($(_carl_utils param-values -f '{quoted_value}' $param))"
	if [[ "$values" ]]; then
	    _values value $values
	fi
}

compdef _carl carl
