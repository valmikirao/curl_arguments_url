#compdef _carl carl

function _carl {
	local line
	_arguments -C '-X:method:(GET POST PUT DELETE PATCH)' '1:url:{_carl_url}' '*::parameter:{_carl_params}'
}

function _carl_utils {
	python -m curl_arguments_url.complete_util $*
}

function _carl_url {
    local -a values
    values=("${(@f)$(_carl_utils zsh-describe-urls-args $opt_args[-X])}")
    if [[ "$values" ]]; then
	    _describe 'url' values
	fi
}

function _carl_params {
	local url param_args
    local -a arguments

	url=$(bash -c 'echo '$line[1])
	if [[ $opt_args[-X] ]]; then
		param_args=(-X $opt_args[-X])
	fi

    arguments=("${(@f)$(_carl_utils params  "$param_args[@]" --format '+{param}[{description}]:value:{{_carl_param_values {param}}}' "$(printf '%b' $url)")}")
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
