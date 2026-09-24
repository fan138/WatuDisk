Get-PhysicalDisk | ForEach-Object {
    $c = $_ | Get-StorageReliabilityCounter
    [PSCustomObject]@{ Id=$_.DeviceId; Bus=$_.BusType; Model=$_.FriendlyName; Temp=$c.Temperature; TempMax=$c.TemperatureMax; Hours=$c.PowerOnHours; Cycles=$c.PowerCycleCount; Wear=$c.Wear; LoadUnload=$c.LoadUnloadCycleCount; StartStop=$c.StartStopCycleCount }
} | ConvertTo-Json
