#compdef _carl carl

function _carl {
	local -a arguments
	arguments=("${(@f)$(_carl_utils zsh-arguments-base-args)}")
	_arguments -C "${arguments[@]}"
}

function _carl_utils {
	python -m curl_arguments_url.complete_util "$@"
}

function _carl_url {
  local method
  local -a values

  method="$(_carl_get_method)"
  values=("${(@f)$(_carl_utils zsh-describe-urls-args "$method")}")

  if [[ "$values" ]]; then
    _describe 'url' values
	fi
}

function _carl_get_method() {
  if [[ "${opt_args[-X]}" ]]; then
		echo "${opt_args[-X]}"
	elif [[ "${opt_args[--method]}" ]]; then
	  echo "${opt_args[--method]}"
	else
	  echo get
	fi
}

function _carl_params {
	local url param_args method
  local -a arguments

	url="$(zsh -c "echo ${line[1]}")"  # the `zsh -c ...` de-escapes the url
  method="$(_carl_get_method)"

  arguments=("${(@f)$(_carl_utils zsh-arguments-params-args "$method" "$url")}")

	if [[ "$arguments" ]]; then
    _arguments "${arguments[@]}"
  fi
}

function _carl_param_values {
	local param
	local -a values

	param=$1
	values=("${(@f)$(_carl_utils param-values "$param")}")

	if [[ "$values" ]]; then
	    _values value $values
	fi
}

compdef _carl carl
