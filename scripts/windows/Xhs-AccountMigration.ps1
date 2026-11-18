# Audited pre-activation schema preservation, not a generic migration bypass.
function Assert-XhsAccountMigrationRevision([string]$Revision, [switch]$After) {
    $expected = if ($After) { 'e61113b0b002' } else { 'e61010a0b001' }
    if ($Revision -cne $expected) { throw "Unexpected XHS account migration revision; expected $expected" }
}

function Assert-XhsAccountPreActivation([string]$MasterEnabled, [string]$CreatorSource) {
    if ($MasterEnabled.Trim().ToLowerInvariant() -notin @('', 'false', '0', 'no', 'off') -or
        $CreatorSource.Trim().ToLowerInvariant() -notin @('', 'browser')) {
        throw 'XHS account schema preservation requires master disabled and creator source browser'
    }
}

function Assert-XhsAccountMigrationPackage([string]$Root) {
    $files = @{
        'e61112a0b001_xhs_cloud_import.py' = '18894dfae62a9dd98a1c165d336c3834ccd4e6872e2b79018bdd07278593c3c6'
        'e61113a0b001_xhs_account_master.py' = 'ee730e4dd680de54b5616aa5cb2b0e97d71fa62607966122028aeda9ba2f3d55'
        'e61113b0b002_xhs_master_cutover.py' = '2a2c9514a83baff038ce0c1b8be32eff1e710fe909dec9307731346c592e1dcb'
    }
    foreach ($name in $files.Keys) {
        $path = Join-Path $Root "backend\app\alembic\versions\$name"
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $files[$name]) {
            throw 'XHS account migration files differ from the audited chain'
        }
    }
}

function Assert-XhsAccountRollbackState([string]$Revision, [long]$NativeRows) {
    if ($Revision -cnotin @('e61010a0b001', 'e61112a0b001', 'e61113a0b001', 'e61113b0b002') -or $NativeRows -ne 0) {
        throw 'Unsafe XHS account rollback: unknown schema or native data; preserve database and require recovery review'
    }
}
