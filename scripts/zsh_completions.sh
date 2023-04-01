#compdef _carl carl

function _carl {
	local -a arguments
	arguments=("${(@f)$(_carl_utils zsh-arguments-base-args)}")
	_arguments -C "$arguments[@]"
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
	local url param_args method
  local -a arguments

	url="$(zsh -c "echo $line[1]")"  # the `zsh -c ...` de-escapes the url
	if [[ $opt_args[-X] ]]; then
		method=$opt_args[-X]
	elif [[ $opt_args[--method] ]]; then
	  method=$opt_args[--method]
	else
	  method=get
	fi

  arguments=("${(@f)$(_carl_utils zsh-arguments-params-args "$method" "$url")}")
	if [[ "$arguments" ]]; then
    _arguments "$arguments[@]"
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
