# bash completion for mad (the MAD Terminal)
_mad() {
    local cur prev words cword
    _init_completion || return
    local commands="test check seal witness dust feed complain ask mcp talk version help fix node tail"
    # Flags work anywhere in mad 0.1.1: complete them when the word
    # starts with a dash, so `mad --<TAB>` teaches the human.
    if [[ $cur == -* ]]; then
        COMPREPLY=( $(compgen -W "--help --version --json" -- "$cur") )
        return
    fi
    local check_sub="agent authorization endpoint"
    local dust_sub="pool ledger balance"
    local complain_sub="file list get"
    local node_sub="start stop status license task serve jobs tape sign anchor key toll"
    case "${words[1]}" in
        node)
            if [[ ${cword} -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$node_sub" -- "$cur") )
            elif [[ ${words[2]} == "serve" ]]; then
                COMPREPLY=( $(compgen -W "--port --host --foreground --json" -- "$cur") )
            elif [[ ${words[2]} == "task" ]]; then
                COMPREPLY=( $(compgen -W "--take --json" -- "$cur") )
            elif [[ ${words[2]} == "tape" ]]; then
                COMPREPLY=( $(compgen -W "--limit --resolve --json" -- "$cur") )
            elif [[ ${words[2]} == "sign" ]]; then
                COMPREPLY=( $(compgen -W "--backfill --block --verify --json" -- "$cur") )
            elif [[ ${words[2]} == "anchor" ]]; then
                COMPREPLY=( $(compgen -W "--block --json" -- "$cur") )
            elif [[ ${words[2]} == "toll" ]]; then
                COMPREPLY=( $(compgen -W "--set-share --json" -- "$cur") )
            elif [[ ${words[2]} == "jobs" ]]; then
                COMPREPLY=( $(compgen -W "--limit --json" -- "$cur") )
            fi
            return ;;
        check)
            if [[ ${cword} -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$check_sub" -- "$cur") )
            elif [[ ${words[2]} == "authorization" ]]; then
                COMPREPLY=( $(compgen -W "--from --to --value --valid-after --valid-before --nonce --chain-id --verifying-contract --now --payment --json" -- "$cur") )
            elif [[ ${words[2]} == "agent" ]]; then
                COMPREPLY=( $(compgen -W "--agent-id --chain --payment --json" -- "$cur") )
            fi
            return ;;
        dust)
            [[ ${cword} -eq 2 ]] && COMPREPLY=( $(compgen -W "$dust_sub" -- "$cur") )
            return ;;
        complain)
            [[ ${cword} -eq 2 ]] && COMPREPLY=( $(compgen -W "$complain_sub" -- "$cur") )
            return ;;
        test)
            COMPREPLY=( $(compgen -W "--agent-id --chain --url --payment --json" -- "$cur") )
            return ;;
        mcp)
            COMPREPLY=( $(compgen -W "--ping --json" -- "$cur") )
            return ;;
        feed)
            COMPREPLY=( $(compgen -W "--limit --json" -- "$cur") )
            return ;;
        seal|witness)
            COMPREPLY=( $(compgen -W "--json" -- "$cur") )
            return ;;
        fix)
            if [[ ${cword} -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "agent seal endpoint authorization last" -- "$cur") )
            fi
            return ;;
    esac
    if [[ ${cword} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
    fi
}
complete -F _mad mad
