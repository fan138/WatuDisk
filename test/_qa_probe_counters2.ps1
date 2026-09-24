Write-Host "=== MSStorageDriver_FailurePredictData (SMART raw) ==="
Get-WmiObject -Namespace root\wmi -Class MSStorageDriver_FailurePredictData -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "InstanceName: $($_.InstanceName)"
    Write-Host "Length: $($_.Length)"
}
Write-Host "=== Get-StorageAdvancedProperty ==="
Get-PhysicalDisk | Get-StorageAdvancedProperty -ErrorAction SilentlyContinue | Format-List | Out-String
Write-Host "=== Get-StorageReliabilityCounter full dump disk0 ==="
Get-PhysicalDisk -DeviceId 0 | Get-StorageReliabilityCounter | Format-List * | Out-String
