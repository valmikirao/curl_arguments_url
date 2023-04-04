#compdef carl

_carl_test_completion() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[carl] )) && return 1

    echo "carl util zsh-completion \"$CURRENT\" \"${words[*]}\""
    completions=("${(@f)$(carl util zsh-completion "$CURRENT" "${words[*]}")}")

    if [ -n "completions" ]; then
        _describe -V unsorted completions -U
    fi
}

compdef _carl_test_completion carl;
